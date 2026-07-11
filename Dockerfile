# Stage 1: Build & install dependencies
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Copy dependency configuration, lock files, and README (required by build backend)
COPY pyproject.toml uv.lock README.md ./

# Install dependencies (without the project itself first, for caching)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --all-extras

# Copy source code and other files needed for build/install
COPY src/ /app/src/

# Install the project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-extras

# Stage 2: Runtime image
FROM python:3.12-slim-bookworm AS runner

# Install cron and tzdata for scheduling and timezone config
RUN apt-get update && apt-get install -y cron tzdata && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy virtual environment
COPY --from=builder /app/.venv /app/.venv

# Copy project source code
COPY src/ /app/src/

# Copy static assets and metadata/cache files
COPY 30_days_words_embeddings.npz /app/
COPY bootstrap.csv /app/
COPY stop_words.txt /app/

# Copy environment example to default .env
COPY .env.example /app/.env

# Set up environment variables and timezone
ENV TZ=America/Chicago
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

ENV PATH="/app/.venv/bin:$PATH"
ENV API_HOST="0.0.0.0"
ENV API_PORT="8000"
ENV HF_HOME="/app/cache/huggingface"

# Ensure log and cache directories exist and are writable
RUN mkdir -p /app/logs /app/cache/huggingface && chmod -R 777 /app/logs /app/cache/huggingface

# Pre-download/cache sentence-transformer model in HF_HOME
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy bootstrap entrypoint script and make it executable
COPY bootstrap.sh /app/bootstrap.sh
RUN chmod +x /app/bootstrap.sh

# Expose FastAPI port
EXPOSE 8000

# Set entrypoint to our bootstrap script
ENTRYPOINT ["/app/bootstrap.sh"]

# Default command is to run the API server
CMD ["word_of_the_day", "--mode", "api"]
