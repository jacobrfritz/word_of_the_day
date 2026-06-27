# src/base_python_project/logger.py
import json
import logging
import os
import sys
import traceback
import uuid
from datetime import date, datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Any


class SafeJSONEncoder(json.JSONEncoder):
    """
    JSON encoder that safely translates non-serializable objects
    (e.g. datetime, UUID, set) to strings instead of raising a TypeError.
    """

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime | date):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


class JSONFormatter(logging.Formatter):
    """
    Structured formatter that compiles LogRecord attributes and any
    extra context into a machine-readable, single-line JSON string.
    """

    def __init__(self) -> None:
        super().__init__()
        # Standard attributes to exclude from extra dynamic context
        self._standard_record_attrs: set[str] = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
            "taskName",
        }

    def format(self, record: logging.LogRecord) -> str:
        # Ensure the message attribute is fully populated
        record.message = record.getMessage()

        # Build structural metadata
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
            "module": record.module,
            "filename": record.filename,
            "func_name": record.funcName,
            "line_no": record.lineno,
            "process_id": record.process,
            "process_name": record.processName,
            "thread_id": record.thread,
            "thread_name": record.threadName,
        }

        # Stash asyncio task name if running in a task in Python 3.12+
        task_name = getattr(record, "taskName", None)
        if task_name:
            log_data["task_name"] = task_name

        # Parse extra custom attributes
        extra: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key not in self._standard_record_attrs:
                extra[key] = value

        if extra:
            log_data["extra"] = extra

        # Extract standard exception formatting
        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            log_data["exception"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value),
                "traceback": traceback.format_exception(exc_type, exc_value, exc_tb),
            }
        elif record.exc_text:
            log_data["exception"] = {
                "message": record.exc_text,
            }

        return json.dumps(log_data, cls=SafeJSONEncoder)


class ConsoleFormatter(logging.Formatter):
    """
    Human-readable log formatter optimized for terminal interfaces.
    Employs beautiful, robust ANSI escape sequences for coloring.
    """

    RESET = "\033[0m"
    DIM = "\033[90m"
    BOLD = "\033[1m"

    COLORS = {
        logging.DEBUG: "\033[36m",  # Cyan
        logging.INFO: "\033[32m",  # Green
        logging.WARNING: "\033[33m",  # Yellow
        logging.ERROR: "\033[31m",  # Red
        logging.CRITICAL: "\033[1;31m",  # Bold Red
    }

    def __init__(self, use_color: bool = True) -> None:
        super().__init__()
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        # Populate the record's main message
        record.message = record.getMessage()

        # Format exact timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        msecs = int(record.msecs)
        time_str = f"{timestamp}.{msecs:03d}"

        # ANSI stylings
        level_color = self.COLORS.get(record.levelno, "") if self.use_color else ""
        reset = self.RESET if self.use_color else ""
        dim = self.DIM if self.use_color else ""
        bold = self.BOLD if self.use_color else ""

        # Build parts of the log header
        parts = [
            f"{dim}[{time_str}]{reset}",
            f"{level_color}{bold}[{record.levelname:<8}]{reset}",
            f"{dim}[{record.filename}:{record.lineno}::{record.funcName}]{reset}",
        ]

        # Process / Thread details
        task_name = getattr(record, "taskName", None)
        sys_info = f"PID:{record.process}::TID:{record.thread}"
        if task_name:
            sys_info += f"::TASK:{task_name}"
        parts.append(f"{dim}[{sys_info}]{reset}")

        # Gather dynamic extra context
        extra_parts = []
        standard_attrs = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
            "taskName",
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs:
                extra_parts.append(f"{key}={value}")

        extra_str = f" {dim}({', '.join(extra_parts)}){reset}" if extra_parts else ""

        # Construct full core message
        main_msg = f"{' '.join(parts)} - {record.message}{extra_str}"

        # Format tracebacks with ANSI red colors if enabled
        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
            if self.use_color:
                colored_tb = "".join(
                    f"{self.COLORS.get(logging.ERROR, '')}{line}{self.RESET}"
                    for line in tb_lines
                )
                main_msg += f"\n{colored_tb}"
            else:
                main_msg += f"\n{''.join(tb_lines)}"
        elif record.exc_text:
            if self.use_color:
                err_color = self.COLORS.get(logging.ERROR, "")
                main_msg += f"\n{err_color}{record.exc_text}{self.RESET}"
            else:
                main_msg += f"\n{record.exc_text}"

        return main_msg


def setup_logging(
    log_file: Path | str | None = None,
    console_level: int | str = logging.INFO,
    file_level: int | str = logging.DEBUG,
    rotation_type: str = "size",
    max_bytes: int = 50 * 1024 * 1024,
    backup_count: int = 10,
    when: str = "midnight",
    interval: int = 1,
    use_color: bool | None = None,
) -> None:
    """
    Configures root logger with console and optional rotating file handlers.

    Args:
        log_file: Path to the log file.
        console_level: Severity threshold for stdout logs.
        file_level: Severity threshold for structured file logs.
        rotation_type: Mode of rolling file: 'size' or 'time'.
        max_bytes: Max size in bytes before rolling.
        backup_count: Maximum backups to retain.
        when: Rollover interval type (e.g. 'midnight').
        interval: Rollover interval scalar.
        use_color: Toggles ANSI colors in console. Auto-detected if None.
    """

    def _parse_level(level: int | str) -> int:
        if isinstance(level, str):
            return getattr(logging, level.upper(), logging.INFO)
        return level

    c_lvl = _parse_level(console_level)
    f_lvl = _parse_level(file_level)

    # Establish root minimum level
    root_level = min(c_lvl, f_lvl) if log_file else c_lvl

    root_logger = logging.getLogger()
    root_logger.setLevel(root_level)

    # Clean existing handlers
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    # 1. Instantiate Console Handler
    if use_color is None:
        use_color = sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
        if use_color and sys.platform == "win32":
            # Enable ANSI escape sequences support on Windows 10+ consoles
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32
                h_stdout = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
                mode = ctypes.c_ulong()
                if kernel32.GetConsoleMode(h_stdout, ctypes.byref(mode)):
                    # ENABLE_VIRTUAL_TERMINAL_PROCESSING is 0x0004
                    kernel32.SetConsoleMode(h_stdout, mode.value | 0x0004)
            except Exception:
                pass

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(c_lvl)
    console_handler.setFormatter(ConsoleFormatter(use_color=use_color))
    root_logger.addHandler(console_handler)

    # 2. Instantiate File Handler (Rotating JSON)
    if log_file:
        file_path = Path(log_file)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if rotation_type.lower() == "size":
            file_handler: RotatingFileHandler | TimedRotatingFileHandler = (
                RotatingFileHandler(
                    file_path,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding="utf-8",
                )
            )
        elif rotation_type.lower() == "time":
            file_handler = TimedRotatingFileHandler(
                file_path,
                when=when,
                interval=interval,
                backupCount=backup_count,
                encoding="utf-8",
            )
        else:
            raise ValueError(
                f"Invalid rotation_type: '{rotation_type}'. "
                "Must be 'size' or 'time'."
            )

        file_handler.setLevel(f_lvl)
        file_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """
    Obtains a logger by name, inheriting the robust parent configuration.
    """
    return logging.getLogger(name)
