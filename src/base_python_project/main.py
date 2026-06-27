# src/base_python_project/main.py
import logging
from pathlib import Path

from .logger import get_logger, setup_logging

logger = get_logger(__name__)


def run() -> None:
    """Core application logic demonstrating the robust logging system."""
    # Configure logging: console logs at INFO level, file logs at DEBUG level
    log_file = Path("logs/app.log")
    setup_logging(
        log_file=log_file,
        console_level=logging.INFO,
        file_level=logging.DEBUG,
        rotation_type="size",
        max_bytes=10 * 1024 * 1024,  # 10MB
        backup_count=5,
    )

    logger.info("Initializing application demo...")
    logger.debug("This is a debug log, visible in the JSON file but not console.")
    logger.info(
        "User logged in successfully",
        extra={
            "user_id": 42,
            "ip_address": "127.0.0.1",
            "session_id": "sess-xyz",
        },
    )
    logger.warning(
        "Disk usage approaching threshold",
        extra={"disk_used_percent": 84.7},
    )

    try:
        # Simulate an exception
        logger.info("Performing a risky mathematical operation...")
        _ = 1 / 0
    except ZeroDivisionError:
        logger.exception("A mathematical error occurred during calculation")

    logger.critical("Demo execution completed successfully.")
