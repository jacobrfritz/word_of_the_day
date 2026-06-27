import os
import shutil
import subprocess
import sys

try:
    import tomllib
except ImportError:
    # Fallback for Python < 3.11 if needed, though project requires 3.12
    import tomllib
from pathlib import Path


def run_command(cmd: list[str] | str, shell: bool = False) -> None:
    try:
        subprocess.run(cmd, check=True, shell=shell)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {cmd}\n{e}")
        sys.exit(1)


def check_and_install_uv() -> None:
    print("Checking for uv...")
    try:
        subprocess.run(
            ["uv", "--version"],
            check=True,
            capture_output=True,
        )
        print("uv is already installed.")
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("uv could not be found, installing...")
        if sys.platform == "win32":
            run_command(
                ["powershell", "-c", "irm https://astral.sh/uv/install.ps1 | iex"]
            )
            # Update PATH for the current session
            os.environ["PATH"] = (
                os.environ.get("PATH", "")
                + os.pathsep
                + os.path.expanduser("~\\.cargo\\bin")
                + os.pathsep
                + os.path.expanduser("~\\.local\\bin")
            )
        else:
            run_command("curl -LsSf https://astral.sh/uv/install.sh | sh", shell=True)
            os.environ["PATH"] = (
                os.environ.get("PATH", "")
                + os.pathsep
                + os.path.expanduser("~/.cargo/bin")
                + os.pathsep
                + os.path.expanduser("~/.local/bin")
            )


def rename_project() -> str | None:
    print("\n--- Project Rename ---")

    # 1. Detect current project name, package name, and script name
    pyproject_path = Path("pyproject.toml")
    current_name = "base-python-project"
    current_pkg = "base_python_project"
    current_script = current_name

    if pyproject_path.exists():
        try:
            with open(pyproject_path, "rb") as f:
                pyproject_data = tomllib.load(f)
                current_name = pyproject_data.get("project", {}).get(
                    "name", current_name
                )

                # Try to find package name and script name from scripts
                scripts = pyproject_data.get("project", {}).get("scripts", {})
                for script_name, entry_point in scripts.items():
                    if ".cli:main" in entry_point:
                        current_pkg = entry_point.split(".")[0]
                        current_script = script_name
                        break
                else:
                    # Fallback to name-based package
                    current_pkg = current_name.replace("-", "_").lower()
                    current_script = current_name
        except Exception:
            pass

    # Try to detect actual package name from src/ if it doesn't match
    src_base = Path("src")
    if src_base.exists() and not (src_base / current_pkg).exists():
        dirs = [
            d for d in src_base.iterdir() if d.is_dir() and (d / "__init__.py").exists()
        ]
        if len(dirs) == 1:
            current_pkg = dirs[0].name

    new_name = input(
        f"Enter the new project name (current: {current_name}) [skip]: "
    ).strip()
    if not new_name or new_name == current_name:
        return None

    pkg_name = new_name.replace("-", "_").lower()
    print(f"Renaming project from {current_name} to {new_name}...")

    # 2. Update pyproject.toml (Deterministic line-by-line)
    if pyproject_path.exists():
        lines = pyproject_path.read_text(encoding="utf-8").splitlines()
        new_lines = []
        in_project_section = False
        in_scripts_section = False

        for line in lines:
            stripped = line.strip()
            if stripped == "[project]":
                in_project_section = True
                in_scripts_section = False
            elif stripped == "[project.scripts]":
                in_project_section = False
                in_scripts_section = True
            elif stripped.startswith("["):
                in_project_section = False
                in_scripts_section = False

            if in_project_section and stripped.startswith("name ="):
                new_lines.append(f'name = "{new_name}"')
            elif in_scripts_section and f'"{current_pkg}.cli:main"' in line:
                # Replace the entire script line: key = "pkg.cli:main"
                new_lines.append(f'{new_name} = "{pkg_name}.cli:main"')
            else:
                new_lines.append(line)
        pyproject_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # 3. Rename src folder
    old_src_dir = src_base / current_pkg
    new_src_dir = src_base / pkg_name
    if old_src_dir.exists() and old_src_dir != new_src_dir:
        print(f"Moving {old_src_dir} to {new_src_dir}...")
        if new_src_dir.exists():
            # Merge if directory exists
            shutil.copytree(old_src_dir, new_src_dir, dirs_exist_ok=True)
            shutil.rmtree(old_src_dir, ignore_errors=True)
        else:
            old_src_dir.rename(new_src_dir)

    # 4. Update references in Python files (Deterministic)
    current_kebab = current_pkg.replace("_", "-")
    new_kebab = new_name.replace("_", "-")
    current_title = current_pkg.replace("_", " ").title()
    new_title = new_name.replace("-", " ").replace("_", " ").title()

    for path in [new_src_dir, Path("tests")]:
        if path.exists():
            for file in path.rglob("*.py"):
                try:
                    content = file.read_text(encoding="utf-8")
                    orig_content = content

                    # Replace snake_case package name
                    content = content.replace(current_pkg, pkg_name)

                    # Replace kebab-case project name
                    content = content.replace(current_kebab, new_kebab)
                    if current_name != current_kebab:
                        content = content.replace(current_name, new_name)

                    # Replace Title Case project name
                    content = content.replace(current_title, new_title)

                    if content != orig_content:
                        file.write_text(content, encoding="utf-8")
                except Exception as e:
                    print(f"Warning: Could not update file {file}: {e}")

    # 5. Update Makefile (Deterministic)
    makefile_path = Path("Makefile")
    if makefile_path.exists():
        try:
            content = makefile_path.read_text(encoding="utf-8")
            orig_content = content

            # Replace snake_case package name
            content = content.replace(current_pkg, pkg_name)

            # Replace kebab-case project name
            content = content.replace(current_kebab, new_kebab)
            if current_name != current_kebab:
                content = content.replace(current_name, new_name)
            if current_script != current_name and current_script != current_pkg:
                content = content.replace(current_script, new_name)

            if content != orig_content:
                makefile_path.write_text(content, encoding="utf-8")
        except Exception as e:
            print(f"Warning: Could not update Makefile: {e}")

    # 6. Update README.md (Deterministic)
    readme_path = Path("README.md")
    if readme_path.exists():
        try:
            content = readme_path.read_text(encoding="utf-8")
            orig_content = content

            # Replace snake_case package name
            content = content.replace(current_pkg, pkg_name)

            # Replace kebab-case project name
            content = content.replace(current_kebab, new_kebab)
            if current_name != current_kebab:
                content = content.replace(current_name, new_name)

            # Replace Title Case project name
            content = content.replace(current_title, new_title)

            if content != orig_content:
                readme_path.write_text(content, encoding="utf-8")
        except Exception as e:
            print(f"Warning: Could not update README.md: {e}")

    return new_name


# Define optional dependency groups available in pyproject.toml
OPTIONAL_GROUPS = {
    "data": "Analytics & Data Manipulation (pandas, numpy, matplotlib, scikit-learn)",
    "ml": "Machine Learning & AI (torch, transformers, huggingface-hub)",
    "api": "Web APIs & Backend (fastapi, uvicorn, pydantic, pydantic-settings)",
    "eng": (
        "Data Engineering & Pipelines (polars, sqlalchemy, psycopg2-binary, pyarrow)"
    ),
    "agents": "Agentic & LLM Tooling (openai, anthropic, instructor)",
    "cli": "Robust Command Line Interfaces (click, rich, typer)",
}


def get_optional_groups_with_deps() -> dict[str, list[str]]:
    lock_path = Path("uv.lock")
    if not lock_path.exists():
        return {}

    try:
        with open(lock_path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return {}

    packages = data.get("package", [])
    for pkg in packages:
        if "optional-dependencies" in pkg:
            optional_deps = pkg["optional-dependencies"]
            result = {}
            for group, deps in optional_deps.items():
                result[group] = [d["name"] for d in deps if "name" in d]
            return result
    return {}


def install_dependencies() -> None:
    print("\n--- Dependencies ---")

    available_groups = get_optional_groups_with_deps()

    if available_groups:
        print("Available optional dependency groups:")
        for group in available_groups:
            description = OPTIONAL_GROUPS.get(group, "")
            if description:
                print(f"  - {group}: {description}")
            else:
                print(f"  - {group}")

    extras = input(
        "\nEnter optional groups to install (comma-separated), or Enter to skip: "
    ).strip()

    req_file = input(
        "Enter a requirements file to install (e.g. requirements.txt), "
        "or Enter to skip: "
    ).strip()

    print("\nSyncing dependencies...")
    sync_cmd = ["uv", "sync"]
    if extras:
        extra_list = [e.strip() for e in extras.split(",") if e.strip()]
        for e in extra_list:
            if e in available_groups or e in OPTIONAL_GROUPS:
                sync_cmd.extend(["--extra", e])
            else:
                print(f"Warning: Unknown dependency group '{e}' - skipping.")

    try:
        run_command(sync_cmd)
    except FileNotFoundError:
        if sys.platform == "win32":
            run_command(sync_cmd, shell=True)
        else:
            raise

    if req_file:
        if Path(req_file).exists():
            add_cmd = ["uv", "add", "-r", req_file]
            try:
                run_command(add_cmd)
            except FileNotFoundError:
                if sys.platform == "win32":
                    run_command(add_cmd, shell=True)
                else:
                    raise
        else:
            print(f"Warning: Requirements file '{req_file}' not found.")


def self_destruct() -> None:
    import time

    # Delete the bootstrap tests file if it exists
    test_file = Path(__file__).parent / "tests" / "test_bootstrap.py"
    try:
        if test_file.exists():
            test_file.unlink()
    except Exception as e:
        print(f"Warning: Could not delete bootstrap tests: {e}")

    print("Self Destructing in:")
    for i in range(5, 0, -1):
        print(f"{i}!")
        time.sleep(0.8)
    print("Caboom")

    # Spawns a background process to delete the file after a short delay
    if os.name == "nt":  # Windows
        cmd = f'timeout /t 1 /nobreak > NUL && del "{__file__}"'
    else:  # Unix/Linux
        cmd = f'sleep 1 && rm "{__file__}"'

    subprocess.Popen(cmd, shell=True)
    sys.exit()


def setup_pre_commit() -> None:
    if Path(".pre-commit-config.yaml").exists():
        print("\n--- Pre-commit Hook Setup ---")
        print("Installing pre-commit hooks...")
        cmd = ["uv", "run", "pre-commit", "install"]
        try:
            if Path(".git").exists():
                run_command(cmd)
                print("Pre-commit hooks successfully installed!")
            else:
                print(
                    "Git repository not detected, "
                    "skipping pre-commit hook installation."
                )
        except FileNotFoundError:
            if sys.platform == "win32":
                try:
                    run_command(cmd, shell=True)
                    print("Pre-commit hooks successfully installed!")
                except Exception as e:
                    print(f"Warning: Could not install pre-commit hooks: {e}")
            else:
                print("uv could not be found to run pre-commit, skipping.")
        except Exception as e:
            print(f"Warning: Could not install pre-commit hooks: {e}")


def main() -> None:
    print("Welcome to the Project Bootstrap!")
    check_and_install_uv()
    new_name = rename_project()
    install_dependencies()
    setup_pre_commit()

    print("\nBootstrap complete!")
    if new_name:
        print(f"You can now run the project with: uv run {new_name}")
    else:
        print("You can now run the project with: uv run base_python_project")
    self_destruct()


if __name__ == "__main__":
    main()
