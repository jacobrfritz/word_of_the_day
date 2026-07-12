from pathlib import Path

from ..logger import get_logger

logger = get_logger(__name__)


def get_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error(
            "The file 'article.txt' does not exist. "
            "Please place a text file or enable the Wikipedia fetcher."
        )
        return None
    except PermissionError:
        logger.error("You do not have permission to access 'article.txt'.")
        return None


def map_source_name(source: str) -> str:
    """
    Maps a raw source key or class name (e.g. 'Gutenberg', 'Wikipedia') to a
    more descriptive and user-friendly name, keeping the scraping aspect hidden.
    """
    if not source:
        return "-"
    
    # Normalize by converting to lowercase and stripping non-alphanumeric chars
    norm = "".join(char for char in source.lower() if char.isalnum())
    
    if norm == "gutenberg":
        return "Classic Books"
    elif norm == "wikipedia":
        return "Encyclopedia"
    elif norm in ("newyorktimes", "nyt"):
        return "News Articles"
    elif norm == "quotable":
        return "Famous Quotes"
    elif norm == "poetrydb":
        return "Classic Poetry"
    elif norm == "substack":
        return "Essays & Articles"
    
    return source

