# src/word_of_the_day/api.py
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from .dictionary import DictionaryClient
from .logger import get_logger
from .storage import Storage, WordOfTheDayRecord

logger = get_logger(__name__)

app = FastAPI(
    title="Word of the Day Portal",
    description="REST API and user interface for the Word of the Day selections.",
    version="1.0.0",
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
                is_valid, definition = dict_client.get_word_definition(word)
                if is_valid:
                    storage.save_word_of_the_day(
                        date=record["date"],
                        word=word,
                        definition=definition,
                        source=record["source"],
                        score=record["score"],
                        extra_info=record["extra_info"],
                    )
                    record["definition"] = definition
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
