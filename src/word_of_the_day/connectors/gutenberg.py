import logging
import random
import time
import urllib.error
from types import TracebackType
from typing import Self

import gutenbergpy.textget

from .protocol import Connector

logger = logging.getLogger(__name__)


class GutenbergAPIError(Exception):
    """Base exception for all Project Gutenberg API/client errors."""

    pass


class GutenbergNetworkError(GutenbergAPIError):
    """Raised when a network timeout or connection failure occurs."""

    pass


class GutenbergRateLimitError(GutenbergAPIError):
    """Raised when rate limits are hit (or suspected)."""

    pass


# A curated list of classic books in Project Gutenberg that contain
# archaic or rare vocabulary
DEFAULT_CLASSIC_IDS = [
    2701,  # Moby Dick; Or, The Whale (Herman Melville)
    1342,  # Pride and Prejudice (Jane Austen)
    11,  # Alice's Adventures in Wonderland (Lewis Carroll)
    1661,  # The Adventures of Sherlock Holmes (Arthur Conan Doyle)
    84,  # Frankenstein; Or, The Modern Prometheus (Mary Wollstonecraft Shelley)
    98,  # A Tale of Two Cities (Charles Dickens)
    174,  # The Picture of Dorian Gray (Oscar Wilde)
    345,  # Dracula (Bram Stoker)
    74,  # The Adventures of Tom Sawyer (Mark Twain)
    1952,  # The Yellow Wallpaper (Charlotte Perkins Gilman)
    120,  # Treasure Island (Robert Louis Stevenson)
    2591,  # Grimms' Fairy Tales (Jacob Grimm and Wilhelm Grimm)
    1400,  # Great Expectations (Charles Dickens)
    2600,  # War and Peace (Leo Tolstoy)
    5200,  # Metamorphosis (Franz Kafka)
    16328,  # Beowulf: An Anglo-Saxon Epic Poem
    1228,  # On the Origin of Species (Charles Darwin)
    43,  # The Strange Case of Dr. Jekyll and Mr. Hyde (Robert Louis Stevenson)
    205,  # Walden, and On The Duty Of Civil Disobedience (Henry David Thoreau)
    100,  # The Complete Works of William Shakespeare (William Shakespeare)
]


class GutenbergClient(Connector):
    """
    A connector to fetch books from Project Gutenberg via gutenbergpy.
    """

    def connector_name(self) -> str:
        return "gutenberg"

    def __init__(
        self,
        book_id: int | str | None = None,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
    ):
        """
        Initialize the Project Gutenberg Client.

        Args:
            book_id: The specific Project Gutenberg book ID to fetch.
                     If None, a random ID from DEFAULT_CLASSIC_IDS is selected.
                     If "random", a random ID from a wider range is selected.
            max_retries: Number of attempts to fetch a book before raising an error.
            backoff_factor: Exponential backoff factor for retries.
        """
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._is_random_discovery = False
        self._random_type = None

        # Determine the book ID to use
        if book_id is None:
            self.book_id = random.choice(DEFAULT_CLASSIC_IDS)
            self._is_random_discovery = True
            self._random_type = "classic"
            logger.info(
                f"No book ID provided. Selected random classic ID: {self.book_id}"
            )
        elif isinstance(book_id, str) and book_id.lower() == "random":
            self.book_id = random.randint(10, 60000)
            self._is_random_discovery = True
            self._random_type = "wide"
            logger.info(f"Selected random book ID from wide range: {self.book_id}")
        else:
            try:
                self.book_id = int(book_id)
                logger.info(f"Using specified book ID: {self.book_id}")
            except ValueError as exc:
                raise GutenbergAPIError(
                    f"Invalid book ID: {book_id}. Must be an integer or 'random'."
                ) from exc

    def fetch_documents(self) -> list[str]:
        """
        Downloads a book from Project Gutenberg and strips its headers and footers,
        then splits the book text into fixed-length documents (chunks of 5,000 words).

        Returns:
            A list of strings, where each string represents a 5,000-word chunk.
        """
        attempt_id = self.book_id

        for attempt in range(self.max_retries):
            try:
                logger.info(
                    f"Attempting to download Gutenberg book ID: {attempt_id} "
                    f"(attempt {attempt + 1}/{self.max_retries})..."
                )

                # Fetch raw content bytes from gutenbergpy
                raw_bytes = gutenbergpy.textget.get_text_by_id(attempt_id)

                if not raw_bytes:
                    raise GutenbergAPIError(
                        f"Downloaded book ID {attempt_id} is empty."
                    )

                # Strip headers and footers to get only the book content
                clean_bytes = gutenbergpy.textget.strip_headers(raw_bytes)

                # Decode to string (using replace error handler to be safe
                # with archaic encodings)
                text = clean_bytes.decode("utf-8", errors="replace")

                # Chunk the book content into 5,000-word segments
                words = text.split()
                chunk_size = 5000
                chunks = []
                for i in range(0, len(words), chunk_size):
                    chunk = " ".join(words[i : i + chunk_size])
                    if chunk.strip():
                        chunks.append(chunk)

                if self._is_random_discovery:
                    if self._random_type == "classic":
                        self.book_id = random.choice(DEFAULT_CLASSIC_IDS)
                    else:
                        self.book_id = random.randint(10, 60000)
                    logger.info(f"Updated book ID for next fetch: {self.book_id}")

                return chunks

            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                OSError,
            ) as exc:
                # Catch rate limits (429) specifically
                if hasattr(exc, "code") and exc.code == 429:  # noqa: B034
                    if attempt == self.max_retries - 1:
                        raise GutenbergRateLimitError(
                            f"Rate limited while downloading Gutenberg book"
                            f" {attempt_id}"
                        ) from exc
                    logger.warning("Rate limit (429) encountered. Retrying...")
                else:
                    if attempt == self.max_retries - 1:
                        raise GutenbergNetworkError(
                            f"Network error while downloading Gutenberg book"
                            f" {attempt_id}"
                        ) from exc
                    logger.warning(f"Transient network error: {exc}. Retrying...")

                sleep_time = (self.backoff_factor**attempt) + random.uniform(0.1, 1.0)
                time.sleep(sleep_time)

            except TypeError as exc:
                # Handle the gutenbergpy bug where bad IDs cause raise None (TypeError)
                logger.error(
                    f"Gutenbergpy internal error or book not found"
                    f" (ID: {attempt_id}): {exc}"
                )

                # If the user requested a specific book ID, we should fail.
                # If we're performing random discovery, we can try another book ID.
                if self._is_random_discovery:
                    logger.info(
                        "Retrying with a different book ID due to"
                        " missing/invalid book..."
                    )
                    if self._random_type == "classic":
                        attempt_id = random.choice(DEFAULT_CLASSIC_IDS)
                    else:
                        attempt_id = random.randint(10, 60000)
                    self.book_id = attempt_id
                else:
                    raise GutenbergAPIError(
                        f"Book ID {attempt_id} could not be resolved"
                        f" or downloaded by gutenbergpy."
                    ) from exc

            except Exception as exc:
                if attempt == self.max_retries - 1:
                    raise GutenbergAPIError(
                        f"Failed to fetch Project Gutenberg book {attempt_id}: {exc}"
                    ) from exc
                logger.warning(f"Unexpected error: {exc}. Retrying...")
                time.sleep(1)

        raise GutenbergAPIError(
            "Unreachable state in Gutenberg client backoff routine."
        )

    def close(self) -> None:
        """No-op for Project Gutenberg client."""
        pass

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
