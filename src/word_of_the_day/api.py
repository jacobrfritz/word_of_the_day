# src/word_of_the_day/api.py
import re
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .config import settings
from .dictionary import DictionaryClient
from .logger import get_logger
from .scheduler import DailyScheduler
from .storage import Storage, WordOfTheDayRecord
from .utils import map_source_name

logger = get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:;"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    if "*" in settings.cors_origins:
        logger.warning(
            "CORS_ORIGINS is set to wildcard '*'. "
            "Restrict this to your production domain(s) before deploying."
        )
    scheduler = DailyScheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.stop()


app = FastAPI(
    title="Word of the Day Portal",
    description="REST API and user interface for the Word of the Day selections.",
    version="1.0.0",
    docs_url=None if settings.disable_api_docs else "/docs",
    redoc_url=None if settings.disable_api_docs else "/redoc",
    openapi_url=None if settings.disable_api_docs else "/openapi.json",
    lifespan=lifespan,
)

# Add Middlewares
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)


def get_storage(request: Request) -> Storage:
    """
    FastAPI dependency provider to return the persistent Storage client.
    Binds the state to the request/app instance to avoid global state issues.
    """
    if not hasattr(request.app.state, "storage"):
        request.app.state.storage = Storage()
    storage = request.app.state.storage
    if isinstance(storage, Storage):
        return storage
    return Storage()


EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class SubscribeRequest(BaseModel):
    email: str


@app.post("/api/subscribe")
def subscribe(
    request: SubscribeRequest,
    storage: Storage = Depends(get_storage),
) -> dict[str, Any]:
    email = request.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")
    if not EMAIL_REGEX.match(email):
        raise HTTPException(status_code=400, detail="Invalid email format.")

    # Check if already subscribed
    sub = storage.get_subscription(email)
    if sub and sub["status"] == "active":
        raise HTTPException(status_code=400, detail="This email is already subscribed.")

    token = uuid.uuid4().hex
    storage.add_subscription(email, token)
    return {"success": True, "message": "Successfully subscribed."}


@app.get("/api/unsubscribe", response_class=HTMLResponse)
def unsubscribe(
    token: str = Query(..., description="The unique unsubscribe token"),
    storage: Storage = Depends(get_storage),
) -> HTMLResponse:
    success = storage.unsubscribe(token)

    if success:
        message_title = "Unsubscribed Successfully"
        message_detail = "You have been unsubscribed from the word. daily digest. We're sorry to see you go!"
    else:
        message_title = "Invalid Token"
        message_detail = "This unsubscribe link is invalid or has already been used."

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{message_title} - Word of the Day</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg-dark: #08080a;
      --bg-card: rgba(18, 18, 22, 0.65);
      --border-color: rgba(209, 178, 128, 0.22);
      --text-primary: #f4f4f5;
      --text-secondary: #d4d4d8;
      --text-muted: #71717a;
      --accent: #d1b280;
      --accent-rgb: 209, 178, 128;
    }}
    body {{
      font-family: 'Inter', sans-serif;
      background-color: var(--bg-dark);
      color: var(--text-primary);
      margin: 0;
      padding: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }}
    .container {{
      max-width: 480px;
      width: 90%;
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: 24px;
      padding: 3rem;
      text-align: center;
      box-shadow: 0 4px 30px rgba(0, 0, 0, 0.4);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
    }}
    h1 {{
      font-family: 'Outfit', sans-serif;
      color: var(--accent);
      font-size: 1.8rem;
      margin-top: 0;
      margin-bottom: 1rem;
    }}
    p {{
      color: var(--text-secondary);
      font-size: 0.95rem;
      line-height: 1.6;
      margin-bottom: 2rem;
    }}
    .back-btn {{
      display: inline-block;
      background: var(--text-primary);
      color: var(--bg-dark);
      text-decoration: none;
      font-family: 'Outfit', sans-serif;
      font-weight: 600;
      font-size: 0.85rem;
      padding: 0.75rem 1.5rem;
      border-radius: 9999px;
      transition: all 0.3s ease;
    }}
    .back-btn:hover {{
      background: var(--accent);
      box-shadow: 0 0 15px 1px rgba(var(--accent-rgb), 0.35);
      transform: translateY(-1px);
    }}
  </style>
</head>
<body>
  <div class="container">
    <h1>{message_title}</h1>
    <p>{message_detail}</p>
    <a href="/" class="back-btn">Go to Portal</a>
  </div>
</body>
</html>
"""
    return HTMLResponse(content=html_content)


@app.get("/api/word", response_model=None)
def get_word(
    date: str | None = Query(
        None, description="Date in YYYY-MM-DD format (defaults to today)"
    ),
    storage: Storage = Depends(get_storage),
) -> WordOfTheDayRecord:
    """
    Returns the Word of the Day record for the specified date.
    If the date has placeholder/empty definition text, it dynamically resolves
    it using DictionaryClient and updates the record (caching it).
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    # Validate date string format
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Expected YYYY-MM-DD."
        ) from e

    # Future dates are not accessible
    today_str = datetime.now().strftime("%Y-%m-%d")
    if date > today_str:
        raise HTTPException(
            status_code=404,
            detail="Word of the Day not available for future dates.",
        )

    record = storage.get_word_of_the_day(date)
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"No Word of the Day has been selected for date {date}.",
        )

    # Self-healing cache: fetch definition if placeholder definition is found
    placeholder = "Historical Word of the Day (definition not loaded)."
    if record["definition"] == placeholder:
        word = record["word"]
        logger.info(f"Resolving definition for historical bootstrapped word: '{word}'")
        try:
            with DictionaryClient(storage=storage) as dict_client:
                is_valid, definition, origin = dict_client.get_word_definition(word)
                if is_valid:
                    storage.save_word_of_the_day(
                        date=record["date"],
                        word=word,
                        definition=definition,
                        source=record["source"],
                        score=record["score"],
                        extra_info=record["extra_info"],
                        origin=origin,
                        cluster_id=record.get("cluster_id"),
                    )
                    record["definition"] = definition
                    record["origin"] = origin
                    logger.info(f"Successfully cached definition for word '{word}'")
                else:
                    logger.warning(
                        f"Could not resolve definition for word '{word}': {definition}"
                    )
        except Exception as e:
            logger.error(f"Error auto-resolving definition for '{word}': {e}")

    record["source"] = map_source_name(record["source"])
    return record


@app.get("/api/dates", response_model=list[str])
def get_dates(storage: Storage = Depends(get_storage)) -> list[str]:
    """
    Returns a sorted list of all dates (YYYY-MM-DD) that have a Word of the Day record.
    Used by the frontend calendar to highlight days with data.
    """
    records = storage.get_history(limit=None)
    today_str = datetime.now().strftime("%Y-%m-%d")
    return sorted({r["date"] for r in records if r["date"] <= today_str})


@app.get("/api/history", response_model=list[WordOfTheDayRecord])
def get_history(
    limit: int | None = Query(
        None, description="Limit the number of history items returned"
    ),
    storage: Storage = Depends(get_storage),
) -> list[WordOfTheDayRecord]:
    """
    Returns historical Word of the Day selections, ordered by date descending.
    """
    records = storage.get_history(limit=None)
    today_str = datetime.now().strftime("%Y-%m-%d")
    filtered_records = [r for r in records if r["date"] <= today_str]
    if limit is not None:
        filtered_records = filtered_records[:limit]
    for r in filtered_records:
        r["source"] = map_source_name(r["source"])
    return filtered_records


_embeddings_grid_cache: dict[str, dict[str, Any]] | None = None
_pca_transformer: Any = None
_kmeans_classifier: Any = None
_embeddings_min_max: tuple[float, float, float, float] | None = None


def _get_base_embeddings_grid() -> (
    tuple[dict[str, dict[str, Any]], Any, Any, tuple[float, float, float, float]]
):
    global \
        _embeddings_grid_cache, \
        _pca_transformer, \
        _kmeans_classifier, \
        _embeddings_min_max
    if _embeddings_grid_cache is not None:
        assert _embeddings_min_max is not None
        return (
            _embeddings_grid_cache,
            _pca_transformer,
            _kmeans_classifier,
            _embeddings_min_max,
        )

    import numpy as np
    from sklearn.cluster import KMeans  # type: ignore[import-untyped]
    from sklearn.decomposition import PCA  # type: ignore[import-untyped]

    from .scorers import EmbeddingScorer

    npz_path = Path(settings.cache_npz_path)
    if not npz_path.exists():
        logger.warning(
            f"Embedding cache not found at {npz_path}. Attempting to compile..."
        )
        try:
            # Recompiling cache by instantiating EmbeddingScorer
            EmbeddingScorer(
                seed_csv_path=settings.seed_csv_path,
                cache_npz_path=settings.cache_npz_path,
                model_name=settings.embedding_model,
                k=settings.embedding_k,
            )
        except Exception as e:
            logger.error(f"Failed to auto-compile embedding cache: {e}")
            raise HTTPException(
                status_code=500,
                detail="Embedding space cache is missing and could not be compiled.",
            ) from e

    try:
        data = np.load(npz_path, allow_pickle=True)
        words = [str(w) for w in data["words"]]
        embeddings = data["embeddings"]
    except Exception as e:
        logger.error(f"Failed to load NPZ cache: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to load embedding database."
        ) from e

    if len(words) == 0:
        raise HTTPException(status_code=500, detail="Embedding database is empty.")

    try:
        scorer = EmbeddingScorer(
            seed_csv_path=settings.seed_csv_path,
            cache_npz_path=settings.cache_npz_path,
            model_name=settings.embedding_model,
            k=settings.embedding_k,
        )
        _, optimal_k = scorer.get_optimal_seed_clusters()
    except Exception as e:
        logger.warning(
            f"Failed to calculate optimal clusters dynamically: {e}. Defaulting to 8 clusters."
        )
        optimal_k = 8

    # Cluster high-dimensional embeddings
    kmeans = KMeans(n_clusters=optimal_k, random_state=42, n_init="auto")
    cluster_ids = kmeans.fit_predict(embeddings)

    # Perform PCA reduction to 2D
    pca = PCA(n_components=2, random_state=42)
    coords_2d = pca.fit_transform(embeddings)

    x_min, x_max = float(coords_2d[:, 0].min()), float(coords_2d[:, 0].max())
    y_min, y_max = float(coords_2d[:, 1].min()), float(coords_2d[:, 1].max())
    _embeddings_min_max = (x_min, x_max, y_min, y_max)

    x_range = x_max - x_min if x_max != x_min else 1.0
    y_range = y_max - y_min if y_max != y_min else 1.0

    _pca_transformer = pca
    _kmeans_classifier = kmeans

    _embeddings_grid_cache = {}
    for i, word in enumerate(words):
        w_clean = word.lower().strip()
        x_val = float((coords_2d[i, 0] - x_min) / x_range)
        y_val = float((coords_2d[i, 1] - y_min) / y_range)
        _embeddings_grid_cache[w_clean] = {
            "word": word,
            "x": x_val,
            "y": y_val,
            "cluster_id": int(cluster_ids[i]),
        }

    return (
        _embeddings_grid_cache,
        _pca_transformer,
        _kmeans_classifier,
        _embeddings_min_max,
    )


@app.get("/api/embeddings/grid")
def get_embeddings_grid(
    storage: Storage = Depends(get_storage),
) -> list[dict[str, Any]]:
    """
    Returns PCA-reduced 2D coordinates and cluster IDs for the vocabulary words.
    Filters the output to only return words present in the selection history.
    """
    try:
        base_cache, pca, kmeans, min_max = _get_base_embeddings_grid()
    except Exception as e:
        logger.error(f"Failed to generate base embeddings: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

    # Fetch all history to cross-reference dates
    history = storage.get_history(limit=None)
    today_str = datetime.now().strftime("%Y-%m-%d")
    history = [h for h in history if h["date"] <= today_str]

    response_data = []
    missing_words = []

    # Map words present in the precomputed cache
    for h in history:
        word_clean = h["word"].lower().strip()
        if word_clean in base_cache:
            item = base_cache[word_clean]
            response_data.append(
                {
                    "word": item["word"],
                    "x": item["x"],
                    "y": item["y"],
                    "cluster_id": item["cluster_id"],
                    "date": h["date"],
                    "source": h["source"],
                }
            )
        else:
            missing_words.append(h)

    # Dynamically encode any manual/organic words not found in the seed set
    if missing_words:
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(settings.embedding_model)

            words_to_encode = [h["word"].strip().lower() for h in missing_words]
            new_embeddings = model.encode(words_to_encode, show_progress_bar=False)

            # Project to 2D and predict clusters using the fitted models
            new_coords_2d = pca.transform(new_embeddings)
            new_cluster_ids = kmeans.predict(new_embeddings)

            x_min, x_max, y_min, y_max = min_max
            x_range = x_max - x_min if x_max != x_min else 1.0
            y_range = y_max - y_min if y_max != y_min else 1.0

            for idx, h in enumerate(missing_words):
                x_val = float((new_coords_2d[idx, 0] - x_min) / x_range)
                y_val = float((new_coords_2d[idx, 1] - y_min) / y_range)

                # Clamp coordinates to [0, 1] bounding box
                x_val = max(0.0, min(1.0, x_val))
                y_val = max(0.0, min(1.0, y_val))

                response_data.append(
                    {
                        "word": h["word"],
                        "x": x_val,
                        "y": y_val,
                        "cluster_id": int(new_cluster_ids[idx]),
                        "date": h["date"],
                        "source": h["source"],
                    }
                )
                logger.info(
                    f"Dynamically mapped embedding for manual word '{h['word']}' to ({x_val:.3f}, {y_val:.3f})"
                )
        except Exception as e:
            logger.error(f"Failed to dynamically embed missing words: {e}")
            # Skip missing words on error instead of throwing 500
            pass

    return response_data


@app.get("/", response_class=HTMLResponse)
def read_root() -> HTMLResponse:
    """
    Serves the beautiful glassmorphic Word of the Day portal dashboard.
    """
    html_path = Path(__file__).parent / "static" / "index.html"
    if not html_path.exists():
        logger.error(f"Static HTML file not found at: {html_path}")
        return HTMLResponse(
            content="<h1>Word of the Day Portal UI not found</h1>", status_code=404
        )

    try:
        content = html_path.read_text(encoding="utf-8")
        return HTMLResponse(content=content)
    except Exception as e:
        logger.error(f"Failed to read static HTML: {e}")
        return HTMLResponse(
            content="<h1>Error loading Word of the Day Portal UI</h1>", status_code=500
        )


@app.get("/healthz", status_code=200)
def health_check(storage: Storage = Depends(get_storage)) -> dict[str, str]:
    """
    Liveness/Readiness probe endpoint.
    Checks if the database is accessible.
    """
    try:
        storage.get_history(limit=1)
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Healthcheck failed: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed") from e


# --- Admin Dashboard Endpoints ---

security = HTTPBearer()


def verify_admin(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
    import hashlib
    import secrets

    token = credentials.credentials
    expected_token = hashlib.sha256(settings.admin_password.encode("utf-8")).hexdigest()
    # Use secrets.compare_digest to prevent timing-based side-channel attacks
    if not secrets.compare_digest(token, expected_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


class LoginRequest(BaseModel):
    password: str


class SaveWordRequest(BaseModel):
    date: str
    word: str
    definition: str | None = None
    source: str | None = None
    origin: str | None = None
    score: float | None = None


class ExploreRequest(BaseModel):
    sources: list[str] | None = ["quotable", "wikipedia"]
    min_score: float | None = 2.3
    max_score: float | None = 4.0
    limit: int | None = 5
    use_embeddings: bool | None = True
    use_lemmatization: bool | None = True


@app.post("/api/admin/login")
def admin_login(payload: LoginRequest) -> dict[str, str]:
    import hashlib

    if payload.password != settings.admin_password:
        raise HTTPException(status_code=401, detail="Invalid password")
    token = hashlib.sha256(payload.password.encode("utf-8")).hexdigest()
    return {"token": token}


@app.get("/admin", response_class=HTMLResponse)
def read_admin() -> HTMLResponse:
    """
    Serves the beautiful glassmorphic Word of the Day admin dashboard.
    """
    html_path = Path(__file__).parent / "static" / "admin.html"
    if not html_path.exists():
        logger.error(f"Static admin HTML file not found at: {html_path}")
        return HTMLResponse(
            content="<h1>Word of the Day Admin UI not found</h1>", status_code=404
        )

    try:
        content = html_path.read_text(encoding="utf-8")
        return HTMLResponse(content=content)
    except Exception as e:
        logger.error(f"Failed to read admin static HTML: {e}")
        return HTMLResponse(
            content="<h1>Error loading Word of the Day Admin UI</h1>", status_code=500
        )


@app.post("/api/admin/word")
def admin_save_word(
    payload: SaveWordRequest,
    storage: Storage = Depends(get_storage),
    _: bool = Depends(verify_admin),
) -> dict[str, str]:
    from wordfreq import zipf_frequency

    try:
        datetime.strptime(payload.date, "%Y-%m-%d")
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Expected YYYY-MM-DD."
        ) from e

    word_clean = payload.word.strip().lower()
    if not word_clean:
        raise HTTPException(status_code=400, detail="Word cannot be empty.")

    definition = payload.definition
    origin = payload.origin
    source = payload.source

    # If definition is not provided, perform automatic lookup and validation
    if not definition:
        from .dictionary import DictionaryClient

        try:
            with DictionaryClient(storage=storage) as dict_client:
                is_valid, resolved_def, resolved_origin = (
                    dict_client.get_word_definition(word_clean)
                )
                if not is_valid:
                    raise HTTPException(
                        status_code=400,
                        detail=f"'{payload.word}' is not a valid dictionary word according to the Merriam-Webster API.",
                    )
                definition = resolved_def
                origin = resolved_origin
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error during dictionary lookup for '{word_clean}': {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error looking up '{payload.word}' definition: {str(e)}",
            ) from e

    if not source:
        source = "Organic"

    score = payload.score
    if score is None:
        score = zipf_frequency(word_clean, "en")

    storage.save_word_of_the_day(
        date=payload.date,
        word=word_clean,
        definition=definition.strip(),
        source=source.strip(),
        score=score,
        extra_info={"manual": True},
        origin=origin,
    )
    return {"status": "success", "word": word_clean}


@app.delete("/api/admin/word")
def admin_delete_word(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    storage: Storage = Depends(get_storage),
    _: bool = Depends(verify_admin),
) -> dict[str, str]:
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Expected YYYY-MM-DD."
        ) from e

    storage.delete_word_of_the_day(date)
    return {"status": "success", "message": f"Deleted word for {date}"}


@app.get("/api/admin/history", response_model=list[WordOfTheDayRecord])
def get_admin_history(
    limit: int | None = Query(
        None, description="Limit the number of history items returned"
    ),
    storage: Storage = Depends(get_storage),
    _: bool = Depends(verify_admin),
) -> list[WordOfTheDayRecord]:
    """
    Returns historical Word of the Day selections including future ones, ordered by date descending.
    """
    records = storage.get_history(limit=limit)
    for r in records:
        r["source"] = map_source_name(r["source"])
    return records


@app.get("/api/admin/stats")
def admin_stats(
    storage: Storage = Depends(get_storage),
    _: bool = Depends(verify_admin),
) -> dict[str, Any]:
    with storage._connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM wotd_history")
        total_words = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM dictionary_cache")
        cache_size = cursor.fetchone()[0]

        cursor.execute("SELECT source, COUNT(*) FROM wotd_history GROUP BY source")
        sources_counts = {row[0]: row[1] for row in cursor.fetchall()}

    db_size = 0
    if storage.db_path.exists():
        db_size = storage.db_path.stat().st_size

    return {
        "total_words": total_words,
        "cache_size": cache_size,
        "sources_counts": sources_counts,
        "db_size_bytes": db_size,
        "db_path": str(storage.db_path),
    }


@app.post("/api/admin/cache/clear")
def admin_clear_cache(
    storage: Storage = Depends(get_storage),
    _: bool = Depends(verify_admin),
) -> dict[str, str]:
    with storage._connect() as conn:
        conn.execute("DELETE FROM dictionary_cache")
        conn.commit()
    return {"status": "success", "message": "Dictionary cache cleared."}


@app.get("/api/admin/logs")
def admin_logs(
    lines: int = Query(100, description="Number of tail lines to retrieve"),
    _: bool = Depends(verify_admin),
) -> dict[str, list[str]]:
    log_path = Path(settings.log_file)
    if not log_path.exists():
        return {"logs": []}
    try:
        content = log_path.read_text(encoding="utf-8").splitlines()
        tail = content[-lines:] if len(content) > lines else content
        return {"logs": tail}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {e}") from e


@app.post("/api/admin/explore")
def admin_explore(
    payload: ExploreRequest,
    storage: Storage = Depends(get_storage),
    _: bool = Depends(verify_admin),
) -> dict[str, list[dict[str, Any]]]:
    from .generator import WordSourceGenerator
    from .main import create_connectors, get_word_scorer
    from .pipeline import WordOfTheDayPipeline
    from .utils import map_source_name

    selected_sources = payload.sources or ["quotable", "wikipedia"]
    if "all" in selected_sources:
        selected_sources = [
            "wikipedia",
            "gutenberg",
            "nyt",
            "quotable",
            "poetry_db",
            "substack",
        ]

    connectors = create_connectors(sources=selected_sources)
    if not connectors:
        raise HTTPException(status_code=400, detail="No valid connectors initialized")

    source_texts: dict[str, str] = {}
    with WordSourceGenerator(connectors) as generator:
        by_connector = generator.fetch_sources_by_connector(count=1, ignore_errors=True)
        if isinstance(by_connector, dict):
            for conn, texts in by_connector.items():
                conn_name = conn.connector_name()
                source_texts[map_source_name(conn_name)] = "\n\n".join(texts)
        else:
            content = generator.fetch_sources(count=1, ignore_errors=True)
            source_texts["Unknown"] = content

    scorer = get_word_scorer(
        use_embeddings=payload.use_embeddings or False,
        seed_csv_path=settings.seed_csv_path,
        cache_npz_path=settings.cache_npz_path,
        embedding_model=settings.embedding_model,
        embedding_k=settings.embedding_k,
    )

    used_words = storage.get_used_words(
        days_threshold=365, reference_date=datetime.now().strftime("%Y-%m-%d")
    )

    def is_reusable_cb(w: str) -> bool:
        return w.lower() not in used_words

    candidates_result = []
    use_lemma = (
        payload.use_lemmatization
        if payload.use_lemmatization is not None
        else settings.use_lemmatization
    )
    with WordOfTheDayPipeline(
        scorer=scorer, storage=storage, use_lemmatization=use_lemma
    ) as pipeline:
        all_scored = []
        for source_name, text in source_texts.items():
            if not text.strip():
                continue
            scored = pipeline.score_candidates(
                text,
                min_score=payload.min_score or 2.3,
                max_score=payload.max_score or 4.0,
                shuffle=False,
                is_reusable_cb=is_reusable_cb,
            )
            for word, score in scored:
                all_scored.append((source_name, word, score))

        seen = {}
        for source_name, word, score in all_scored:
            word_lower = word.lower()
            if word_lower not in seen:
                seen[word_lower] = (source_name, score)
            else:
                existing_source, existing_score = seen[word_lower]
                if scorer.higher_is_better and score > existing_score:
                    seen[word_lower] = (source_name, score)
                elif not scorer.higher_is_better and score < existing_score:
                    seen[word_lower] = (source_name, score)

        merged_scored = [(src, w, s) for w, (src, s) in seen.items()]
        merged_scored.sort(key=lambda item: item[2], reverse=scorer.higher_is_better)

        scored_pairs = [(w, s) for _, w, s in merged_scored]
        validated = pipeline.validate_candidates(scored_pairs, limit=payload.limit or 5)

        word_to_source = {w: src for src, w, _ in merged_scored}
        for c in validated:
            candidates_result.append(
                {
                    "word": c.word,
                    "definition": c.definition,
                    "score": c.score if c.score is not None else c.zipf_score,
                    "zipf_score": c.zipf_score,
                    "source": word_to_source.get(c.word, "Unknown"),
                    "origin": c.origin,
                }
            )

    return {"candidates": candidates_result}
