# tests/test_logger.py
import json
import logging
import sys
import uuid
from collections.abc import Generator
from datetime import datetime
from pathlib import Path

import pytest
from word_of_the_day.logger import (
    ConsoleFormatter,
    JSONFormatter,
    SafeJSONEncoder,
    get_logger,
    setup_logging,
)


def test_safe_json_encoder() -> None:
    """
    Verifies that SafeJSONEncoder successfully encodes standard and
    non-standard types, and falls back gracefully to str representation
    for un-serializable objects.
    """

    class UnserializableClass:
        def __str__(self) -> str:
            return "unserializable_str"

    encoder = SafeJSONEncoder()
    now = datetime(2026, 5, 31, 10, 0, 0)
    uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    unserializable = UnserializableClass()

    assert encoder.default(now) == "2026-05-31T10:00:00"
    assert encoder.default(uid) == "12345678-1234-5678-1234-567812345678"
    assert encoder.default(b"hello bytes") in ("hello", "hello bytes")
    assert encoder.default(unserializable) == "unserializable_str"

    # Test set serialization
    encoded_set = encoder.default({1, 2, 3})
    assert set(encoded_set) == {1, 2, 3}


def test_json_formatter_basic() -> None:
    """
    Verifies that the JSONFormatter converts a standard LogRecord
    into the expected structured JSON format.
    """
    formatter = JSONFormatter()
    logger = logging.getLogger("test_json")
    record = logger.makeRecord(
        name="test_json",
        level=logging.INFO,
        fn="test_file.py",
        lno=42,
        msg="Test message with %s",
        args=("arg1",),
        exc_info=None,
        func="test_function",
    )

    formatted_str = formatter.format(record)
    log_dict = json.loads(formatted_str)

    assert log_dict["level"] == "INFO"
    assert log_dict["logger"] == "test_json"
    assert log_dict["message"] == "Test message with arg1"
    assert log_dict["filename"] == "test_file.py"
    assert log_dict["func_name"] == "test_function"
    assert log_dict["line_no"] == 42
    assert "timestamp" in log_dict
    assert "process_id" in log_dict
    assert "thread_id" in log_dict


def test_json_formatter_extra_context() -> None:
    """
    Verifies that JSONFormatter captures custom variables passed in
    the `extra` argument.
    """
    formatter = JSONFormatter()
    logger = logging.getLogger("test_json_extra")
    record = logger.makeRecord(
        name="test_json_extra",
        level=logging.WARNING,
        fn="test_file.py",
        lno=50,
        msg="Warning message",
        args=(),
        exc_info=None,
        func="test_function",
    )
    # Inject extra attributes
    record.__dict__["user_id"] = 12345
    record.__dict__["request_id"] = "req-abc"

    formatted_str = formatter.format(record)
    log_dict = json.loads(formatted_str)

    assert log_dict["level"] == "WARNING"
    assert log_dict["extra"]["user_id"] == 12345
    assert log_dict["extra"]["request_id"] == "req-abc"


def test_json_formatter_exception() -> None:
    """
    Verifies that exception information is captured and structured properly
    inside the JSON payload.
    """
    formatter = JSONFormatter()
    logger = logging.getLogger("test_json_exc")

    try:
        raise ValueError("Something went wrong!")
    except ValueError:
        exc_info = sys.exc_info()

    record = logger.makeRecord(
        name="test_json_exc",
        level=logging.ERROR,
        fn="test_file.py",
        lno=60,
        msg="An error occurred",
        args=(),
        exc_info=exc_info,
        func="test_function",
    )

    formatted_str = formatter.format(record)
    log_dict = json.loads(formatted_str)

    assert log_dict["level"] == "ERROR"
    assert log_dict["exception"]["type"] == "ValueError"
    assert "Something went wrong!" in log_dict["exception"]["message"]
    assert isinstance(log_dict["exception"]["traceback"], list)
    assert len(log_dict["exception"]["traceback"]) > 0


def test_console_formatter_basic() -> None:
    """
    Verifies that ConsoleFormatter produces readable logs, both with
    and without colors.
    """
    # Without color
    formatter_no_color = ConsoleFormatter(use_color=False)
    logger = logging.getLogger("test_console")
    record = logger.makeRecord(
        name="test_console",
        level=logging.INFO,
        fn="test_file.py",
        lno=42,
        msg="Test message",
        args=(),
        exc_info=None,
        func="test_function",
    )

    formatted_str = formatter_no_color.format(record)

    assert "[INFO    ]" in formatted_str
    assert "[test_file.py:42::test_function]" in formatted_str
    assert "Test message" in formatted_str
    assert "\033" not in formatted_str  # Ensure no ANSI escape codes are present

    # With color
    formatter_color = ConsoleFormatter(use_color=True)
    formatted_color_str = formatter_color.format(record)

    assert "[INFO    ]" in formatted_color_str
    assert "\033[" in formatted_color_str  # Ensure ANSI colors are present


@pytest.fixture
def clean_logger_handlers() -> Generator[None, None, None]:
    """Fixture to ensure root logger handlers are clean before and after tests."""
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    yield
    # Restore
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
    for handler in original_handlers:
        root_logger.addHandler(handler)


def test_setup_logging_console(clean_logger_handlers: None) -> None:
    """
    Verifies that setup_logging successfully configures the root logger
    with a console handler.
    """
    setup_logging(console_level="DEBUG", use_color=False)
    root_logger = logging.getLogger()

    assert len(root_logger.handlers) == 1
    console_handler = root_logger.handlers[0]
    assert isinstance(console_handler, logging.StreamHandler)
    assert console_handler.level == logging.DEBUG
    assert isinstance(console_handler.formatter, ConsoleFormatter)


def test_setup_logging_dual(clean_logger_handlers: None, tmp_path: Path) -> None:
    """
    Verifies that setup_logging successfully configures both a console
    and a JSON rotating file handler.
    """
    log_file = tmp_path / "app.log"
    setup_logging(
        log_file=log_file,
        console_level=logging.WARNING,
        file_level=logging.DEBUG,
        rotation_type="size",
        max_bytes=1000,
        backup_count=3,
        use_color=False,
    )

    root_logger = logging.getLogger()
    assert len(root_logger.handlers) == 2

    # Check Console handler
    console_handler = next(
        h for h in root_logger.handlers if isinstance(h, logging.StreamHandler)
    )
    assert console_handler.level == logging.WARNING
    assert isinstance(console_handler.formatter, ConsoleFormatter)

    # Check File handler
    file_handler = next(
        h for h in root_logger.handlers if isinstance(h, logging.FileHandler)
    )
    assert file_handler.level == logging.DEBUG
    assert isinstance(file_handler.formatter, JSONFormatter)

    # Write some logs and verify file exists
    logger = get_logger("my_module")
    logger.debug("Debug log message")
    logger.warning("Warning log message", extra={"user": "bob"})

    # Ensure log file exists and contains JSON entries
    assert log_file.exists()
    lines = log_file.read_text("utf-8").splitlines()
    assert len(lines) == 2

    log1 = json.loads(lines[0])
    assert log1["level"] == "DEBUG"
    assert log1["message"] == "Debug log message"
    assert log1["logger"] == "my_module"

    log2 = json.loads(lines[1])
    assert log2["level"] == "WARNING"
    assert log2["message"] == "Warning log message"
    assert log2["extra"]["user"] == "bob"
