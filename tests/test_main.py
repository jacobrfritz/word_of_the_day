# tests/test_main.py
import pytest
from base_python_project import main


def test_run(capsys: pytest.CaptureFixture[str]) -> None:
    main.run()
    captured = capsys.readouterr()
    # Check that stdout has captured console formatting logs
    assert "Initializing application demo..." in captured.out
    assert "User logged in successfully" in captured.out
    assert "Disk usage approaching threshold" in captured.out
    assert "ZeroDivisionError" in captured.out
    assert "Demo execution completed successfully." in captured.out
