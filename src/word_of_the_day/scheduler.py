# src/word_of_the_day/scheduler.py
import threading
import time
from datetime import datetime, timedelta

try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo  # type: ignore

from .config import settings
from .logger import get_logger

logger = get_logger(__name__)


class DailyScheduler:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not settings.scheduler_enabled:
            logger.info("Scheduler is disabled in configuration.")
            return
        logger.info("Starting background scheduler...")
        self._thread = threading.Thread(
            target=self._run, name="WotdScheduler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        logger.info("Stopping background scheduler...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _sleep_interruptible(self, seconds: float) -> bool:
        """Sleep for the given number of seconds, returning False early if stopped."""
        chunk_size = 10
        slept = 0.0
        while slept < seconds:
            if self._stop_event.is_set():
                return False
            time.sleep(min(chunk_size, seconds - slept))
            slept += chunk_size
        return True

    def _run_with_retries(
        self, max_retries: int = 3, retry_delay_seconds: int = 1800
    ) -> bool:
        """
        Run the word-selection subprocess with retries on failure.
        Returns True if any attempt succeeds.
        """
        import subprocess
        import sys

        for attempt in range(max_retries + 1):
            if self._stop_event.is_set():
                return False
            try:
                logger.info(
                    f"Running scheduled word selection "
                    f"(attempt {attempt + 1}/{max_retries + 1})..."
                )
                result = subprocess.run(
                    [sys.executable, "-m", "word_of_the_day.cli", "--mode", "auto"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                logger.info("Scheduled word selection completed successfully.")
                if result.stdout:
                    logger.debug(f"Subprocess stdout:\n{result.stdout}")
                return True
            except subprocess.CalledProcessError as e:
                logger.error(
                    f"Subprocess failed (attempt {attempt + 1}) with exit code "
                    f"{e.returncode}.\nStdout: {e.stdout}\nStderr: {e.stderr}",
                    exc_info=True,
                )
            except Exception as e:
                logger.error(
                    f"Error in scheduled task (attempt {attempt + 1}): {e}",
                    exc_info=True,
                )

            if attempt < max_retries:
                delay_min = retry_delay_seconds // 60
                logger.info(
                    f"Retrying word selection in {delay_min} minutes "
                    f"(attempt {attempt + 2}/{max_retries + 1})..."
                )
                if not self._sleep_interruptible(retry_delay_seconds):
                    return False

        logger.error(
            f"Word selection failed after {max_retries + 1} attempts. "
            "Will retry at next scheduled midnight run."
        )
        return False

    def _run(self) -> None:
        # Wait a bit on startup to allow API server to start fully
        time.sleep(5)
        while not self._stop_event.is_set():
            self._run_with_retries()

            # Calculate sleep time until next midnight in America/Chicago
            try:
                tz = zoneinfo.ZoneInfo("America/Chicago")
            except Exception:
                try:
                    tz = zoneinfo.ZoneInfo("UTC")
                except Exception:
                    tz = None

            now = datetime.now(tz)
            # Calculate next midnight
            next_run = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            sleep_seconds = (next_run - now).total_seconds()

            logger.info(
                f"Next scheduled run at: {next_run.isoformat()} "
                f"(sleeping for {sleep_seconds:.1f}s)"
            )

            self._sleep_interruptible(sleep_seconds)
