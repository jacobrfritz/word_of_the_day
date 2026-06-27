# base_python_project

A robust default Python project template using `uv`.

## Setup

This project uses `uv` for dependency management and includes a bootstrapping script to quickly get you started.

To bootstrap the project, run:

```bash
python bootstrap.py
```

The bootstrap script will:
- **Check for `uv`**: Automatically installs [uv](https://github.com/astral-sh/uv) if it's not already on your system.
- **Rename Project**: Guides you through renaming the project and its Python package from the default `base_python_project`.
- **Sync Dependencies**: Installs project dependencies and allows you to select optional extras (e.g., `data`, `ml`, `api`).
- **Reset Git**: Optionally clears the template's git history and initializes a new repository for your project.

## Usage

Common development tasks can be run using either the `Makefile` (convenient for Unix-like environments and CI) or directly via `uv` (recommended on Windows or when you need to pass additional command-line arguments).

### Development Commands

| Task | Make Command | Direct `uv` Command | Description |
| :--- | :--- | :--- | :--- |
| **Sync Dependencies** | `make install` | `uv sync` | Install or sync project dependencies. |
| **Run CLI** | `make run` | `uv run base_python_project` | Run the application command-line interface. |
| **Run Tests** | `make test` | `uv run pytest` | Run the test suite. |
| **Watch Tests** | `make test-watch` | `uv run ptw` | Run tests in watch mode. |
| **Coverage Report** | `make test-cov` | `uv run pytest --cov=src --cov-report=term-missing` | Run tests and generate coverage. |
| **Lint Code** | `make lint` | `uv run ruff check .` | Check style and quality with Ruff. |
| **Format Code** | `make format` | `uv run ruff format .` | Format code using Ruff. |
| **Type Check** | `make typecheck` | `uv run mypy src` | Run static type analysis with mypy. |

### Passing Arguments

One of the main advantages of running commands directly via `uv` is the ability to easily append any standard command-line arguments. For example:

* **Run a specific test:**
  ```bash
  uv run pytest -k test_some_feature
  ```
* **Auto-fix lint issues:**
  ```bash
  uv run ruff check . --fix
  ```


## Project Structure

```text
.
├── .editorconfig
├── .gitignore
├── .pre-commit-config.yaml
├── Makefile
├── README.md
├── bootstrap.py
├── pyproject.toml
├── uv.lock
├── src/
│   └── base_python_project/
│       ├── __init__.py
│       ├── cli.py
│       └── main.py
└── tests/
    ├── __init__.py
    └── test_main.py
```

- `src/`: Core application logic.
- `tests/`: Project tests.
- `pyproject.toml`: Project metadata and dependencies.
- `bootstrap.py`: Interactive setup script.
- `Makefile`: Shortcuts for common tasks.
