# Word of the Day Portal & Pipeline

A comprehensive daily vocabulary generator, analytics pipeline, and Jinja2-powered portal dashboard. The application extracts word candidates from a variety of digital text sources, filters them using lemmatization, Part-of-Speech, and length constraints, ranks them using semantic embeddings or TF-IDF, calculates semantic word similarity links, validates candidates on-demand via the Merriam-Webster API with SQLite caching, picks final words using Softmax temperature selection, serves interactive views via FastAPI and Jinja2 server-side templating, and delivers daily newsletter digests.

---

## Features

- **Multi-Source Corpus Ingestion**: Fetches raw texts from Wikipedia, Project Gutenberg (by ID or random), the New York Times API, Quotable API, PoetryDB, and Substack publication feeds in parallel, working alongside cached words in the local SQLite database.
- **Word Source Tracking**: Retains the origin/source of each cached candidate word (e.g., `gutenberg`, `wikipedia`, `substack`) throughout database queries, scoring, and client-facing displays.
- **Jinja2 Server-Side Templating & Modular UI**: Replaces legacy static pages with a modular Jinja2 template hierarchy featuring base layout inheritance (`layouts/base.html`), dynamic theme switching, and reusable components (`navbar`, `vote_widget`, `subscribe_form`, `theme_switcher`).
- **Dedicated Word Pages & Spatial Map**:
  - `GET /word/{word}`: Dedicated deep-linking word detail page displaying etymology, definition, pronunciation, voting status, and semantically related words.
  - `GET /map`: Interactive 2D embedding space visualization rendering semantic clusters and historical vocabulary distribution.
  - `GET /unsubscribe`: Dedicated portal for subscriber management and one-click unsubscribing.
- **Semantic Word Similarity & Related Word Discovery**: Uses K-Nearest Neighbors on SentenceTransformer vector embeddings (`scorers.py`) to compute cosine similarity between words, persisting related words and similarity scores (`word_similarity` database table) for interactive vocabulary exploration.
- **Interactive Voting & Community Reactions**: Allows users to upvote or downvote words (`POST /api/vote`) with session-tracked rate-limiting. Net voting scores are stored in SQLite and displayed across dashboard cards and word pages.
- **Softmax Temperature Selection Strategy**: Probability-based word selection scaled by a configurable temperature parameter (`softmax` vs `argmax`), allowing tunable creativity and semantic variety.
- **Daily Email Newsletter Pipeline**:
  - Dispatches responsive HTML newsletter emails rendered via Jinja2 templates (`templates/emails/daily_digest.html`) to active subscribers daily at 6:00 AM.
  - Standard RFC-compliant bulk newsletter headers (`List-Unsubscribe`, bulk headers, and plain-text fallback content).
  - Configurable daily limit protection (`SMTP_MAX_EMAILS_PER_DAY`) with administrator alert emails when thresholds are reached.
- **Part-of-Speech & Length Filtering**: Uses NLTK's averaged perceptron tagger to filter candidate nouns, adjectives, and verbs within configurable length bounds (`MIN_WORD_LENGTH`, `MAX_WORD_LENGTH`).
- **Dynamic Semantic Clustering & Rotation**: Seed embeddings are clustered via K-Means (optimal $K$ determined on-the-fly via the Elbow Method). The pipeline rotates to the next cluster daily, scoring candidates against the active cluster centroid.
- **FastAPI Backend Server**:
  - `GET /`: Serves the main glassmorphic analytics dashboard.
  - `GET /subscribe`: Serves the email newsletter subscription portal.
  - `GET /word/{word}`: Serves the dedicated word detail view.
  - `GET /map`: Serves the interactive 2D embedding vocabulary map.
  - `GET /unsubscribe`: Serves the unsubscribe confirmation page.
  - `GET /admin`: Serves the password-protected admin dashboard.
  - `GET /api/word?date=YYYY-MM-DD`: Returns word selection for a date (with self-healing dictionary validation fallback).
  - `POST /api/vote`: Upvotes, downvotes, or clears user votes on words.
  - `GET /api/dates`: Returns a sorted list of dates with selected words.
  - `GET /api/history?limit=N`: Fetches recent historical selections.
  - `GET /api/embeddings/grid`: Returns PCA-reduced 2D coordinates and cluster IDs for embedding visualizer.
  - `GET /healthz`: Database liveness/readiness container health probe.
  - `POST /api/subscribe`: Subscribes a new email address.
  - `GET /api/unsubscribe?token=TOKEN`: Safe one-click unsubscribe endpoint.
  - `POST /api/admin/login`: Admin authentication endpoint.
  - `POST /api/admin/word`: Manually saves a word for a given date.
  - `DELETE /api/admin/word?date=YYYY-MM-DD`: Removes a word entry for a specific date.
  - `GET /api/admin/history`: Retrieves word history for admin management.
  - `GET /api/admin/stats`: Returns database statistics (total words, cache sizes, subscription counts, DB size).
  - `POST /api/admin/cache/clear`: Purges the dictionary validation cache.
  - `POST /api/admin/send-email`: Triggers a manual email newsletter dispatch.
  - `GET /api/admin/logs?lines=N`: Returns recent application logs.
  - `POST /api/admin/explore`: Runs live candidate exploration across selected text sources.
- **Admin Dashboard**: Web interface for word management, candidate exploration, email dispatching, log monitoring, and system metrics.
- **Robust Background Scheduler**: Daemon thread scheduler managing daily word generation subprocesses and email dispatch routines without memory leaks.
- **Security & Container Readiness**: Hardened FastAPI security headers (CSP, HSTS, CORS), non-root Docker execution (`appuser`), pre-baked ML models, and Docker Compose orchestration.

---

## Architecture & Data Flow

The diagram below outlines how text is ingested, filtered, scored, semantically linked, persisted, and served:

```mermaid
graph TD
    A[Digital Text Sources<br>Wikipedia, Gutenberg, NYT, etc.] --> B[Text Cleaning & Tokenization<br>Lowercase, punctuation removal, lemmatization]
    B --> C{Selection Mode?}
    C -- Yes --> D[365-day Reuse Check<br>Filter out recently selected words]
    C -- No --> E[POS & Length Filter<br>Filter for nouns/adjectives/verbs & length bounds]
    D --> E
    E --> F[Scoring Candidates<br>Rank via Embedding, TF-IDF, or Zipf scorers]
    F --> G[Deduplication & Sorting<br>Sort by score & preserve source metadata]
    G --> H[Lazy Dictionary Validation<br>Validate via MW API with SQLite caching]
    H --> I{Selection Mode?}
    I -- Yes --> J[Word Selection Strategy<br>HighestScore or TemperatureSoftmax selection]
    I -- No --> K[List Candidates<br>Display scored candidates]
    J --> L[Semantic Similarity Engine<br>Compute cosine similarity & link top related words]
    L --> M[SQLite Database<br>Save word, definitions, votes, sources & similarity links]
    M --> N[FastAPI + Jinja2 Server<br>Render SSR views: /, /word/{word}, /map, /subscribe]
    M --> O[Daily Email Newsletter<br>Dispatch Jinja2 HTML email at 6:00 AM]
    K --> N
```

### Detailed Processing Steps

1. **Ingestion**: Raw text corpora are retrieved from Wikipedia, Project Gutenberg, New York Times API, Quotable API, PoetryDB, or Substack publication feeds in parallel.
2. **Text Cleaning & Tokenization**: Text is lowercased, non-alphabetic characters removed, stop words filtered, and base forms extracted via Simplemma lemmatization.
3. **Reusability Check**: Filters out candidates selected within the last 365 days.
4. **POS, Length, & Zipf Frequency Filtering**: Retains target parts-of-speech (nouns, adjectives, verbs) within length bounds (`MIN_WORD_LENGTH`, `MAX_WORD_LENGTH`) and goldilocks Zipf frequency ranges (`MIN_SCORE`, `MAX_SCORE`).
5. **Scoring & Semantic Rotation**: Candidates are scored against active cluster centroids (K-Means with Elbow Method optimal $K$), TF-IDF vectors, or Zipf rarity scores.
6. **Dictionary Validation & Persistence**: Validates real English words via Merriam-Webster API, stores etymologies, definitions, source attribution, and `cluster_id` in SQLite.
7. **Semantic Linking**: Computes vector similarity for the picked word using `EmbeddingScorer.get_similar_words()` and stores top related words in the `word_similarity` database table.
8. **Templated Serving & Email Dispatch**: Jinja2 templates dynamically render dashboard pages, word detail pages (`/word/{word}`), spatial embedding maps (`/map`), and daily HTML email digests.

---

## Setup & Installation

This project uses `uv` for fast dependency and environment management.

### Prerequisites

Install `uv` if you haven't already:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Installation

Sync all dependencies (including `jinja2`, `fastapi`, `sentence-transformers`, `wordfreq`, etc.):
```bash
make install
```
*(Equivalent to running `uv sync`)*

### Environment Configuration

Copy the sample environment file:
```bash
cp .env.example .env
```

Key environment variables in `.env`:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `NYT_API_KEY` | *(empty)* | Required if using the New York Times connector. |
| `MERRIAM_WEBSTER_API_KEY` | *(empty)* | Required for dictionary validation. |
| `MIN_SCORE` | `2.3` | Lower bound of the Zipf frequency range. |
| `MAX_SCORE` | `4.0` | Upper bound of the Zipf frequency range. |
| `LIMIT` | `3` | Number of candidates to validate/extract per source. |
| `USE_EMBEDDINGS` | `True` | Toggle semantic embedding scoring. |
| `SELECTION_STRATEGY` | `softmax` | Word selection strategy (`softmax` or `argmax`). |
| `SELECTION_TEMPERATURE` | `1.0` | Softmax temperature parameter. |
| `USE_LEMMATIZATION` | `True` | Toggle lemmatizing words via Simplemma. |
| `POS_FILTER_NOUNS` | `True` | Keep and filter candidate nouns. |
| `POS_FILTER_ADJECTIVES` | `True` | Keep and filter candidate adjectives. |
| `POS_FILTER_VERBS` | `True` | Keep and filter candidate verbs. |
| `MIN_WORD_LENGTH` | *(empty)* | Minimum length bounds of candidate words. |
| `MAX_WORD_LENGTH` | *(empty)* | Maximum length bounds of candidate words. |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | SentenceTransformer model name. |
| `EMBEDDING_K` | `5` | Fixed cluster count override. |
| `SEED_CSV_PATH` | `word_of_the_day_embeddings.csv` | Path to seed word list CSV. |
| `CACHE_NPZ_PATH` | `word_of_the_day_embeddings.npz` | Path to precomputed embedding cache. |
| `DB_PATH` | *(project root)* | Override SQLite database path. |
| `ADMIN_PASSWORD` | `admin123` | Password for the `/admin` dashboard. |
| `CORS_ORIGINS` | `["*"]` | Allowed origins for CORS. |
| `DISABLE_API_DOCS` | `False` | Set to `True` to hide `/docs` and `/redoc`. |
| `SCHEDULER_ENABLED` | `True` | Toggle daily background scheduler. |
| `SMTP_BACKEND` | `console` | SMTP backend (`smtp` or `console`). |
| `SMTP_HOST` | `localhost` | Host for SMTP server. |
| `SMTP_PORT` | `587` | Port for SMTP server. |
| `SMTP_USERNAME` | *(empty)* | Username for SMTP auth. |
| `SMTP_PASSWORD` | *(empty)* | Password for SMTP auth. |
| `SMTP_FROM_EMAIL` | `noreply@wordoftheday.com` | Sender address for daily emails. |
| `SMTP_FROM_NAME` | `word.` | Sender display name. |
| `SMTP_USE_TLS` | `True` | Toggle TLS for SMTP transport. |
| `SMTP_USE_SSL` | `False` | Toggle SSL for SMTP transport. |
| `SMTP_MAX_EMAILS_PER_DAY` | `200` | Daily limit on newsletter email sends. |
| `SMTP_ADMIN_NOTIFICATION_EMAIL` | *(empty)* | Alert recipient when email quota is reached. |
| `APP_BASE_URL` | `http://localhost:8000` | Base URL for links in email digests. |
| `LOG_FILE` | `logs/app.log` | Rotating log file path. |
| `LOG_LEVEL` | `INFO` | Root log level. |

### Running the App Locally

#### 1. Start the API Server & Templated UI
```bash
uv run word_of_the_day --mode api
```
Access the application interfaces at `http://127.0.0.1:8000`:
- **Dashboard**: http://127.0.0.1:8000
- **Word Detail View**: http://127.0.0.1:8000/word/serendipity
- **Vocabulary Map**: http://127.0.0.1:8000/map
- **Newsletter Subscription**: http://127.0.0.1:8000/subscribe
- **Admin Dashboard**: http://127.0.0.1:8000/admin (Default password: `admin123`)

#### 2. Run CLI Operations
```bash
# List candidates from Wikipedia
uv run word_of_the_day --mode list --source wikipedia

# Run auto selection for today
uv run word_of_the_day --mode auto

# Manually set a word
uv run word_of_the_day --mode set --word "sagacious" --date 2026-07-22

# Send daily newsletter emails
uv run word_of_the_day --mode send-emails --date 2026-07-22
```

---

## Usage & Commands

All development tasks are pre-configured in the `Makefile`.

| Task | Make Command | Direct `uv` Command | Description |
| :--- | :--- | :--- | :--- |
| **Sync Dependencies** | `make install` | `uv sync` | Synchronize package dependencies. |
| **Run Default CLI** | `make run` | `uv run word_of_the_day` | Runs the CLI app with defaults. |
| **Run Tests** | `make test` | `uv run pytest` | Run the unit and integration test suite. |
| **Watch Tests** | `make test-watch` | `uv run ptw` | Run tests in watch mode. |
| **Coverage Report** | `make test-cov` | `uv run pytest --cov=src ...` | Run tests and generate coverage. |
| **Lint Code** | `make lint` | `uv run ruff check .` | Run style checks with Ruff. |
| **Format Code** | `make format` | `uv run ruff format .` | Format codebase using Ruff. |
| **Type Check** | `make typecheck` | `uv run mypy src` | Run static type analysis with mypy. |

---

## Project Structure

```text
.
├── Dockerfile                        # Multi-stage slim non-root Docker runtime config
├── Makefile                          # Commands for local development and testing
├── README.md                         # Project documentation
├── bootstrap_word_of_the_day.py      # Seed word syncing from MW podcast RSS feed
├── docker-compose.yml                # Docker Compose config with volume mounts
├── pyproject.toml                    # UV project configuration and dependencies (Jinja2, FastAPI, etc.)
├── stop_words.txt                    # Configurable stop words list for tokenization
├── word_of_the_day.db                # SQLite database (history, votes, similarity, subscribers)
├── word_of_the_day_embeddings.csv    # Seed word list
├── word_of_the_day_embeddings.npz    # Precomputed embeddings cache
├── src/
│   └── word_of_the_day/
│       ├── connectors/               # Source connectors (Wikipedia, Gutenberg, NYT, etc.)
│       ├── static/                   # CSS, client JavaScript modules (index.js, word.js, style.css)
│       ├── templates/                # Jinja2 SSR Templates & UI Components
│       │   ├── layouts/              # Base layout templates (base.html)
│       │   ├── components/           # Reusable components (navbar, vote_widget, theme_switcher, etc.)
│       │   ├── emails/               # Daily HTML email templates (daily_digest.html)
│       │   ├── index.html            # Main dashboard template
│       │   ├── word.html             # Single word detail page template
│       │   ├── map.html              # Vocabulary 2D spatial map template
│       │   ├── subscribe.html        # Newsletter subscription portal template
│       │   ├── unsubscribe.html      # Unsubscribe confirmation template
│       │   └── admin.html            # Password-protected admin dashboard template
│       ├── utils/                    # Common text helpers and source mapping
│       ├── api.py                    # FastAPI server: Jinja2 route handlers, vote & admin endpoints
│       ├── cli.py                    # CLI argument parser and entry point
│       ├── config.py                 # Pydantic Settings configuration (reads .env)
│       ├── dictionary.py             # Merriam-Webster API client & SQLite dictionary caching
│       ├── email_sender.py           # Newsletter dispatch engine via Jinja2 HTML email templates
│       ├── generator.py              # Candidate word parser from raw source text
│       ├── main.py                   # CLI orchestrator & pipeline runner
│       ├── pipeline.py               # Candidate scoring and pipeline orchestration
│       ├── scheduler.py              # Background daemon thread scheduler
│       ├── scorers.py                # EmbeddingScorer (with KNN similarity), ZipfScorer, TF-IDF
│       ├── selectors.py              # Word selector strategies (HighestScore & TemperatureSoftmax)
│       └── storage.py                # SQLite database manager (word history, votes, word_similarity)
└── tests/                            # Comprehensive unit & integration test suite
    ├── test_api.py                   # API routes and Jinja2 rendering tests
    ├── test_email_pipeline.py        # Integration and unit tests for SMTP/console email dispatching
    ├── test_scorers.py               # Vector embedding and KNN similarity test suite
    ├── test_storage.py               # Storage, voting, and similarity schema migration tests
    └── ...                           # Other module-specific test suites
```

---

## Container Deployment

The application is containerized and published on Docker Hub as `hateyoujake/word_of_the_day:latest` with production-grade security defaults:
- **Official Image**: `hateyoujake/word_of_the_day:latest`
- **Non-Root User**: The container runs under `appuser` (UID `10001`), ensuring compatibility with strict container security policies (e.g., Kubernetes root restrictions).
- **Pre-baked ML Model**: The `all-MiniLM-L6-v2` SentenceTransformer model is downloaded during the Docker build and cached in the image, so the container starts without requiring a network download.
- **Auto-Bootstrap**: On startup, if no seed CSV is found at `SEED_CSV_PATH`, the container automatically runs `bootstrap_word_of_the_day.py` to seed the word list from the Merriam-Webster podcast RSS feed.
- **Health Checks**: A liveness/readiness probe checks `/healthz` on a 30s interval.

### Pulling Pre-built Container

You can pull the official pre-built image directly from Docker Hub:
```bash
docker pull hateyoujake/word_of_the_day:latest
```

### Running with Docker Compose (Recommended)

Starts the FastAPI server using `hateyoujake/word_of_the_day:latest` with a host bind mount (mapping the project root) for the SQLite database, embeddings, and seed CSV:

```bash
docker compose up -d
```

The portal will be available at [http://localhost:8001](http://localhost:8001) (or `http://localhost:8000`) and the admin dashboard at `/admin`.

The host project root directory is bind mounted to `/app/db` inside the container. The environment in `docker-compose.yml` sets the database and seed paths to this directory:
```yaml
services:
  word_of_the_day:
    image: hateyoujake/word_of_the_day:latest
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8001:8001"
    volumes:
      - .:/app/db
      - ./logs:/app/logs
    env_file:
      - .env
    environment:
      - API_HOST=0.0.0.0
      - API_PORT=8001
      - DB_PATH=/app/db/word_of_the_day.db
      - SEED_CSV_PATH=/app/db/word_of_the_day_embeddings.csv
      - CACHE_NPZ_PATH=/app/db/word_of_the_day_embeddings.npz
```

### Running with Docker CLI

1. **Build the Image**
   ```bash
   docker build -t hateyoujake/word_of_the_day:latest .
   ```

2. **Run the API Server**
   ```bash
   docker run -d \
     -p 8001:8001 \
     --name wotd-api \
     -v $(pwd):/app/db \
     -v $(pwd)/logs:/app/logs \
     -e DB_PATH=/app/db/word_of_the_day.db \
     -e SEED_CSV_PATH=/app/db/word_of_the_day_embeddings.csv \
     -e CACHE_NPZ_PATH=/app/db/word_of_the_day_embeddings.npz \
     --env-file .env \
     hateyoujake/word_of_the_day:latest
   ```

3. **Run One-off CLI Pipeline Modes**
   ```bash
   # List candidates
   docker run --rm hateyoujake/word_of_the_day:latest --mode list

   # Auto-select today's word
   docker run --rm \
     -v $(pwd):/app/db \
     -e DB_PATH=/app/db/word_of_the_day.db \
     hateyoujake/word_of_the_day:latest --mode auto
   ```

### Multi-Platform & macOS Builds (Docker Buildx)

When building on macOS (especially Apple Silicon M1/M2/M3/M4 or Intel Macs), `docker buildx` is recommended to ensure correct cross-platform compilation and multi-architecture image creation (`linux/amd64` and `linux/arm64`).

1. **Create and Initialize a Buildx Builder Instance** (required once on macOS):
   ```bash
   docker buildx create --name wotd-builder --use
   docker buildx inspect --bootstrap
   ```

2. **Build and Load Image Locally on macOS**:
   To build for your local Mac architecture and load it directly into Docker Desktop:
   ```bash
   docker buildx build -t hateyoujake/word_of_the_day:latest --load .
   ```

3. **Build and Push Multi-Platform Manifest (amd64 + arm64)**:
   To cross-compile and push the multi-architecture manifest list to Docker Hub:
   ```bash
   docker buildx build \
     --platform linux/amd64,linux/arm64 \
     -t hateyoujake/word_of_the_day:latest \
     --push .
   ```

---

## Admin Dashboard

Access `/admin` with your configured `ADMIN_PASSWORD` (default: `admin123`):
- **Word Management**: Add or delete words by date.
- **Email Newsletter Dispatch**: Manually trigger daily email digest delivery.
- **Live Exploration**: Run candidate pipelines interactively against selected sources.
- **Database Stats**: Monitor word history, subscribers, vote counts, cache size, and DB file size.
- **Log Viewer & Cache Cleared**: View real-time application logs and clear dictionary cache.
