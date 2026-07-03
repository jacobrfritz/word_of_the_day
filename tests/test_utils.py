# tests/test_utils.py
from pathlib import Path
from unittest.mock import patch

import pytest
from word_of_the_day.utils import get_text


def test_get_text_success(tmp_path: Path) -> None:
    """Verifies that get_text successfully reads a file that exists."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello World", encoding="utf-8")

    content = get_text(str(test_file))
    assert content == "Hello World"


def test_get_text_file_not_found(caplog: pytest.LogCaptureFixture) -> None:
    """Verifies that get_text returns None and logs an error when a file is missing."""
    content = get_text("nonexistent_file_xyz_123.txt")
    assert content is None
    # Verify the error is logged
    assert any(
        "The file 'article.txt' does not exist." in record.message
        for record in caplog.records
    )


def test_get_text_permission_error(caplog: pytest.LogCaptureFixture) -> None:
    """Verifies that get_text returns None and logs an error on PermissionError."""
    with patch.object(
        Path, "read_text", side_effect=PermissionError("Permission denied")
    ):
        content = get_text("article.txt")
        assert content is None
        assert any(
            "You do not have permission to access 'article.txt'." in record.message
            for record in caplog.records
        )
