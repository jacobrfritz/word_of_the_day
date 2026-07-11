# word_of_the_day

A robust default Python project template using `uv`.

## Setup

This project uses `uv` for dependency management and includes a bootstrapping script to quickly get you started.

To bootstrap the project, run:

```bash
python bootstrap.py
```

The bootstrap script will:
- **Check for `uv`**: Automatically installs [uv](https://github.com/astral-sh/uv) if it's not already on your system.
- **Rename Project**: Guides you through renaming the project and its Python package from the default `word_of_the_day`.
- **Sync Dependencies**: Installs project dependencies and allows you to select optional extras (e.g., `data`, `ml`, `api`).
- **Reset Git**: Optionally clears the template's git history and initializes a new repository for your project.

## Usage

Common development tasks can be run using either the `Makefile` (convenient for Unix-like environments and CI) or directly via `uv` (recommended on Windows or when you need to pass additional command-line arguments).

### Development Commands

| Task | Make Command | Direct `uv` Command | Description |
| :--- | :--- | :--- | :--- |
| **Sync Dependencies** | `make install` | `uv sync` | Install or sync project dependencies. |
| **Run CLI** | `make run` | `uv run word_of_the_day` | Run the application command-line interface. |
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
│   └── word_of_the_day/
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


## Docker Support

This project can be fully containerized using Docker and Docker Compose. The Docker image uses a multi-stage build powered by `uv` for fast dependency installation and minimal final image size. It also pre-downloads the default Hugging Face SentenceTransformer model (`all-MiniLM-L6-v2`) to ensure offline compatibility.

### Daily Word Generation Cron Job

When running in containerized mode (e.g. via Docker or Docker Compose), a system cron daemon is automatically installed and configured to run the auto-selection pipeline (`word_of_the_day --mode auto`) once daily at midnight Central Time (`America/Chicago`).

- **Timezone**: The container's timezone is set to `America/Chicago` to guarantee accurate timezone-relative daily runs.
- **Logging**: The cron execution logs are routed directly back to the container's stdout/stderr, so you can inspect daily runs via standard container logs (e.g., `docker logs` or `docker compose logs`).

### Building the Image

Build the Docker image locally:

```bash
docker build -t word-of-the-day .
```

### Running with Docker Compose (Recommended)

Running via Docker Compose is the easiest way to start the FastAPI server and keep your data persisted.

1. Start the API server in background mode:
   ```bash
   docker compose up -d
   ```
   The FastAPI server will be available at `http://localhost:8000`.

2. Stop the API server:
   ```bash
   docker compose down
   ```

### Running with Docker CLI

You can also run the container directly using the `docker` command.

#### Run the API Server (Default)

```bash
docker run -d \
  -p 8000:8000 \
  --name wotd-api \
  -v $(pwd)/word_of_the_day.db:/app/word_of_the_day.db \
  -v $(pwd)/logs:/app/logs \
  --env-file .env \
  word-of-the-day
```

#### Run CLI Commands

You can run CLI commands by overriding the default command:

```bash
# List word candidates from all sources
docker run --rm word-of-the-day --mode list

# Automatically select the word of the day
docker run --rm \
  -v $(pwd)/word_of_the_day.db:/app/word_of_the_day.db \
  word-of-the-day --mode auto
```

#### Run Tests Inside the Container

To verify the test suite runs correctly inside the container:

```bash
docker run --rm --entrypoint pytest word-of-the-day
```

