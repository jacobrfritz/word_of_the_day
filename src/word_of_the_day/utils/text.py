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
