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

    def _run(self) -> None:
        # Wait a bit on startup to allow API server to start fully
        time.sleep(5)
        while not self._stop_event.is_set():
            try:
                # Import run inside to avoid circular dependencies
                from .main import run

                logger.info("Running scheduled word selection...")
                run(mode="auto")
            except Exception as e:
                logger.error(f"Error in scheduled task: {e}", exc_info=True)

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
                f"Next scheduled run at: {next_run.isoformat()} (sleeping for {sleep_seconds:.1f}s)"
            )

            # Sleep in chunks to allow quick shutdown
            chunk_size = 10
            slept = 0
            while slept < sleep_seconds:
                if self._stop_event.is_set():
                    break
                time.sleep(min(chunk_size, sleep_seconds - slept))
                slept += chunk_size
