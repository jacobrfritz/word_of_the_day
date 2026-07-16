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
        self._email_thread: threading.Thread | None = None

    def start(self) -> None:
        if not settings.scheduler_enabled:
            logger.info("Scheduler is disabled in configuration.")
            return
        logger.info("Starting background scheduler...")
        self._thread = threading.Thread(
            target=self._run, name="WotdScheduler", daemon=True
        )
        self._thread.start()

        self._email_thread = threading.Thread(
            target=self._run_email_dispatch, name="WotdEmailScheduler", daemon=True
        )
        self._email_thread.start()

    def stop(self) -> None:
        logger.info("Stopping background scheduler...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._email_thread:
            self._email_thread.join(timeout=5)

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
                # 1. Run bootstrap to fetch new words
                from pathlib import Path
                project_root = Path(__file__).resolve().parents[2]
                bootstrap_script = project_root / "bootstrap_word_of_the_day.py"
                if bootstrap_script.exists():
                    try:
                        logger.info(f"Running daily bootstrap: {bootstrap_script} (attempt {attempt + 1})")
                        bootstrap_result = subprocess.run(
                            [sys.executable, str(bootstrap_script)],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        if bootstrap_result.returncode == 0:
                            logger.info("Daily bootstrap completed successfully.")
                            if bootstrap_result.stdout:
                                logger.debug(f"Bootstrap stdout:\n{bootstrap_result.stdout}")
                        else:
                            logger.warning(
                                f"Daily bootstrap finished with non-zero exit code {bootstrap_result.returncode}.\n"
                                f"Stderr: {bootstrap_result.stderr}"
                            )
                    except Exception as e:
                        logger.warning(f"Error running daily bootstrap: {e}", exc_info=True)
                else:
                    logger.warning(f"Bootstrap script not found at expected path: {bootstrap_script}")

                # 2. Run the main word-selection subprocess
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

    def _run_email_dispatch(self) -> None:
        # Wait on startup to let DB initialize and API start
        time.sleep(10)
        while not self._stop_event.is_set():
            try:
                from .email_sender import check_and_send_daily_emails
                check_and_send_daily_emails()
            except Exception as e:
                logger.error(f"Error in email dispatch: {e}", exc_info=True)

            try:
                tz = zoneinfo.ZoneInfo("America/Chicago")
            except Exception:
                try:
                    tz = zoneinfo.ZoneInfo("UTC")
                except Exception:
                    tz = None

            now = datetime.now(tz)
            # Calculate next 6:00 AM
            next_run = now.replace(hour=6, minute=0, second=0, microsecond=0)
            if now >= next_run:
                next_run += timedelta(days=1)
            sleep_seconds = (next_run - now).total_seconds()

            logger.info(
                f"Next scheduled email dispatch at: {next_run.isoformat()} "
                f"(sleeping for {sleep_seconds:.1f}s)"
            )

            if not self._sleep_interruptible(sleep_seconds):
                break
