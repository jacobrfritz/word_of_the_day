# src/word_of_the_day/api.py
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .dictionary import DictionaryClient
from .logger import get_logger
from .storage import Storage, WordOfTheDayRecord
from .config import settings
from .scheduler import DailyScheduler

logger = get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
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
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
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

storage = Storage()


@app.get("/api/word", response_model=None)
def get_word(
    date: str | None = Query(
        None, description="Date in YYYY-MM-DD format (defaults to today)"
    ),
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
            with DictionaryClient() as dict_client:
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

    return record


@app.get("/api/history", response_model=list[WordOfTheDayRecord])
def get_history(
    limit: int | None = Query(
        None, description="Limit the number of history items returned"
    ),
) -> list[WordOfTheDayRecord]:
    """
    Returns historical Word of the Day selections, ordered by date descending.
    """
    return storage.get_history(limit=limit)


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
def health_check() -> dict[str, str]:
    """
    Liveness/Readiness probe endpoint.
    Checks if the database is accessible.
    """
    try:
        storage.get_history(limit=1)
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Healthcheck failed: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed")
