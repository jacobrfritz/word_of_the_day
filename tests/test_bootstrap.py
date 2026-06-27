import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# Add the project root to sys.path to import bootstrap
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import bootstrap


def test_run_command_success() -> None:
    # Test a simple successful command using python to be cross-platform
    bootstrap.run_command([sys.executable, "-c", "print('hello')"])


def test_run_command_failure() -> None:
    # Test a failing command raises SystemExit
    with pytest.raises(SystemExit):
        bootstrap.run_command([sys.executable, "-c", "import sys; sys.exit(1)"])


def test_get_optional_groups_with_deps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Create a dummy uv.lock file
    uv_lock = tmp_path / "uv.lock"
    uv_lock.write_text(
        """
[[package]]
name = "foo"
version = "0.1.0"

[package.optional-dependencies]
dev = [
    { name = "pytest", version = ">=7.0.0" },
    { name = "black", version = ">=22.0.0" }
]
test = [
    { name = "tox", version = ">=3.0.0" }
]
""",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    groups = bootstrap.get_optional_groups_with_deps()

    assert groups == {"dev": ["pytest", "black"], "test": ["tox"]}


def test_get_optional_groups_with_deps_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    groups = bootstrap.get_optional_groups_with_deps()
    assert groups == {}


def test_rename_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Setup mock project structure
    monkeypatch.chdir(tmp_path)

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "base-python-project"\n'
        "\n"
        "[project.scripts]\n"
        'base-project = "base_python_project.cli:main"',
        encoding="utf-8",
    )

    makefile = tmp_path / "Makefile"
    makefile.write_text("run: uv run base-project", encoding="utf-8")

    src_dir = tmp_path / "src" / "base_python_project"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").touch()

    main_py = src_dir / "main.py"
    main_py.write_text('print("base-python-project")', encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_main_py = tests_dir / "test_main.py"
    test_main_py.write_text(
        "from base_python_project import main\n"
        'assert "base-python-project" == "base-python-project"',
        encoding="utf-8",
    )

    # Mock input to provide new project name
    inputs = iter(["new-project"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    new_name = bootstrap.rename_project()

    assert new_name == "new-project"

    # Verify file content updates
    assert 'name = "new-project"' in pyproject.read_text(encoding="utf-8")
    assert 'new-project = "new_project.cli:main"' in pyproject.read_text(
        encoding="utf-8"
    )
    assert "uv run new-project" in makefile.read_text(encoding="utf-8")

    # Verify directory rename
    assert not src_dir.exists()
    assert (tmp_path / "src" / "new_project").exists()
    assert (tmp_path / "src" / "new_project" / "__init__.py").exists()

    # Verify src file content
    # Note: We now replace both imports and strings inside files.
    src_content = (tmp_path / "src" / "new_project" / "main.py").read_text(
        encoding="utf-8"
    )
    assert 'print("new-project")' in src_content

    # Verify test file content
    test_content = test_main_py.read_text(encoding="utf-8")
    assert "from new_project import main" in test_content
    assert 'assert "new-project" == "new-project"' in test_content


def test_rename_project_different_pkg_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Setup mock project structure where package name doesn't match project name
    monkeypatch.chdir(tmp_path)

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "base-python-project"\n'
        "\n"
        "[project.scripts]\n"
        'base-project = "test_pkg.cli:main"',
        encoding="utf-8",
    )

    makefile = tmp_path / "Makefile"
    makefile.write_text("run: uv run base-project", encoding="utf-8")

    src_dir = tmp_path / "src" / "test_pkg"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").touch()

    main_py = src_dir / "main.py"
    main_py.write_text('print("base-python-project")', encoding="utf-8")

    # Mock input to provide new project name
    inputs = iter(["new-project"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    new_name = bootstrap.rename_project()

    assert new_name == "new-project"

    # Verify file content updates
    content = pyproject.read_text(encoding="utf-8")
    assert 'name = "new-project"' in content
    assert 'new-project = "new_project.cli:main"' in content

    # Verify directory rename
    assert not src_dir.exists()
    assert (tmp_path / "src" / "new_project").exists()


def test_rename_project_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    # Mock input to skip
    monkeypatch.setattr("builtins.input", lambda _: "")

    new_name = bootstrap.rename_project()
    assert new_name is None


def test_install_dependencies_basic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    # Mock get_optional_groups_with_deps to return empty
    monkeypatch.setattr(bootstrap, "get_optional_groups_with_deps", lambda: {})

    # Mock inputs: extras="", req_file=""
    inputs = iter(["", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    # Track calls to run_command
    calls = []

    def mock_run_command(cmd: Any, shell: bool = False) -> None:
        calls.append(cmd)

    monkeypatch.setattr(bootstrap, "run_command", mock_run_command)

    bootstrap.install_dependencies()

    assert ["uv", "sync"] in calls


def test_install_dependencies_with_extras_and_reqs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    # Mock get_optional_groups_with_deps
    monkeypatch.setattr(
        bootstrap, "get_optional_groups_with_deps", lambda: {"dev": ["pytest"]}
    )

    # Create a requirements.txt
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("requests", encoding="utf-8")

    # Mock inputs: extras="dev", req_file="requirements.txt"
    inputs = iter(["dev", "requirements.txt"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    # Track calls to run_command
    calls = []

    def mock_run_command(cmd: Any, shell: bool = False) -> None:
        calls.append(cmd)

    monkeypatch.setattr(bootstrap, "run_command", mock_run_command)

    bootstrap.install_dependencies()

    assert ["uv", "sync", "--extra", "dev"] in calls
    assert ["uv", "add", "-r", "requirements.txt"] in calls


def test_check_and_install_uv_already_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mock subprocess.run to simulate uv --version success
    def mock_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if cmd == ["uv", "--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"uv 0.1.0")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    # This should not call run_command for installation
    calls = []

    def mock_run_command(cmd: Any, shell: bool = False) -> None:
        calls.append(cmd)

    monkeypatch.setattr(bootstrap, "run_command", mock_run_command)

    bootstrap.check_and_install_uv()

    assert len(calls) == 0


def test_check_and_install_uv_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock subprocess.run to simulate uv --version failure (FileNotFoundError)
    def mock_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if cmd == ["uv", "--version"]:
            raise FileNotFoundError()
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    # This SHOULD call run_command for installation
    calls = []

    def mock_run_command(cmd: Any, shell: bool = False) -> None:
        calls.append(cmd)

    monkeypatch.setattr(bootstrap, "run_command", mock_run_command)

    # Mock sys.platform to something known
    monkeypatch.setattr(sys, "platform", "linux")

    bootstrap.check_and_install_uv()

    assert len(calls) == 1
    assert "https://astral.sh/uv/install.sh" in calls[0]


def test_setup_pre_commit_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    # Create mock files
    config_file = tmp_path / ".pre-commit-config.yaml"
    config_file.touch()

    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    calls = []

    def mock_run_command(cmd: Any, shell: bool = False) -> None:
        calls.append(cmd)

    monkeypatch.setattr(bootstrap, "run_command", mock_run_command)

    bootstrap.setup_pre_commit()

    assert ["uv", "run", "pre-commit", "install"] in calls


def test_setup_pre_commit_no_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    calls = []

    def mock_run_command(cmd: Any, shell: bool = False) -> None:
        calls.append(cmd)

    monkeypatch.setattr(bootstrap, "run_command", mock_run_command)

    bootstrap.setup_pre_commit()

    assert len(calls) == 0
