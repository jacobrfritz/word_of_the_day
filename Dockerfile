# Stage 1: Build & install dependencies
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Copy dependency configuration and lock files (README.md is not needed by uv sync --no-install-project)
COPY pyproject.toml uv.lock ./

# Install dependencies (without the project itself, for caching)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --all-extras

# Stage 2: Runtime image
FROM python:3.12-slim-bookworm AS runner

# Install tzdata for timezone configuration
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*

# Set up environment variables and timezone
ENV TZ=America/Chicago
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV API_HOST="0.0.0.0"
ENV API_PORT="8000"
ENV HF_HOME="/app/cache/huggingface"

# Create directories and set up non-root user
RUN groupadd -g 10001 appgroup && \
    useradd -r -u 10001 -g appgroup appuser && \
    mkdir -p /app/logs /app/cache/huggingface && \
    touch /app/word_of_the_day.db && \
    chown -R appuser:appgroup /app && \
    chmod -R 775 /app/logs /app/cache/huggingface /app/word_of_the_day.db

# Create a wrapper script so that the 'word_of_the_day' executable name still works
RUN echo '#!/bin/sh\nif [ ! -f /app/bootstrap.csv ] && [ ! -f /app/word_of_the_day_embeddings.csv ]; then\n  echo "No seed CSV files found. Running bootstrap_word_of_the_day.py..."\n  python /app/bootstrap_word_of_the_day.py\nfi\nexec python -m word_of_the_day.cli "$@"' > /usr/local/bin/word_of_the_day && \
    chmod +x /usr/local/bin/word_of_the_day

# Copy virtual environment (cached unless dependencies in uv.lock change)
COPY --from=builder /app/.venv /app/.venv

# Run model pre-download as root so it is cached in the image system-wide, but change ownership afterwards.
# This runs after the virtual environment is copied, but BEFORE any project source code is copied.
# This ensures that editing src/ files doesn't trigger a redownload of the ML model!
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" && \
    chown -R appuser:appgroup /app/cache/huggingface

# Copy static assets and metadata/cache files
COPY --chown=appuser:appgroup bootstrap_word_of_the_day.py /app/
COPY --chown=appuser:appgroup stop_words.txt /app/
COPY --chown=appuser:appgroup .env.example /app/.env

# Copy project source code
COPY --chown=appuser:appgroup src/ /app/src/

# Switch to the non-root user
USER 10001

# Expose FastAPI port
EXPOSE 8000

# Healthcheck to verify FastAPI service status
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

# Default command is to run the API server
ENTRYPOINT ["word_of_the_day"]
CMD ["--mode", "api"]
