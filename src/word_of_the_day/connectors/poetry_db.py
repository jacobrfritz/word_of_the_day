import logging
import os
import random
import time
import urllib.parse
from collections.abc import Callable
from types import TracebackType
from typing import Self

import httpx

from .protocol import Connector

logger = logging.getLogger(__name__)


class PoetryDBAPIError(Exception):
    """Base exception for all PoetryDB API client errors."""

    pass


class PoetryDBRateLimitError(PoetryDBAPIError):
    """Raised when the client is rate-limited (HTTP 429) by PoetryDB."""

    def __init__(self, retry_after: int = 60, message: str = "Rate limit exceeded"):
        self.retry_after = retry_after
        super().__init__(f"{message}. Please retry after {retry_after} seconds.")


class PoetryDBNetworkError(PoetryDBAPIError):
    """Raised when a network timeout or connection failure occurs."""

    pass


DEFAULT_CLASSIC_POETS = [
    "Edgar Allan Poe",
    "George Gordon, Lord Byron",
    "Percy Bysshe Shelley",
    "John Keats",
    "William Shakespeare",
    "Emily Dickinson",
    "Lord Alfred Tennyson",
    "Oscar Wilde",
    "Walt Whitman",
    "William Wordsworth",
    "John Milton",
    "Elizabeth Barrett Browning",
    "Robert Browning",
    "Samuel Taylor Coleridge",
    "William Blake",
    "Christina Rossetti",
    "Ralph Waldo Emerson",
]


class PoetryDBClient(Connector):
    """
    A robust client for fetching random classic poems from the PoetryDB API.
    """

    BASE_URL = "https://poetrydb.org"

    def connector_name(self) -> str:
        return "poetry_db"

    def __init__(
        self,
        author: str | list[str] | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
    ):
        """
        Initialize the PoetryDB Client.

        Args:
            author: A specific author name, a list of author names,
                    "any" for global random, or None/"random" to pick
                    randomly from a curated list of classic authors.
            timeout: Network timeout in seconds.
            max_retries: Number of attempts for transient errors before failing.
        """
        if author is not None and not isinstance(author, str | list):
            raise PoetryDBAPIError(
                "author must be None, a string, or a list of strings."
            )

        self.author = author
        self.max_retries = max_retries
        self.timeout = timeout

        app_name = os.environ.get("POETRY_DB_APP_NAME") or os.environ.get(
            "APP_NAME", "WordOfTheDay"
        )
        version = os.environ.get("POETRY_DB_VERSION") or os.environ.get(
            "APP_VERSION", "1.0"
        )
        contact_email = os.environ.get("POETRY_DB_CONTACT_EMAIL") or os.environ.get(
            "CONTACT_EMAIL", "fritz@example.com"
        )

        # Compliant headers
        headers = {
            "User-Agent": (
                f"{app_name}/{version} (contact: {contact_email})"
                f" httpx/{httpx.__version__}"
            ),
            "Accept": "application/json; charset=utf-8",
        }

        self.client = httpx.Client(
            base_url=os.environ.get("POETRY_DB_BASE_URL", self.BASE_URL),
            headers=headers,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        )

    def _execute_with_backoff(
        self, request_fn: Callable[[], httpx.Response]
    ) -> httpx.Response:
        """
        Executes a network request using exponential backoff with jitter.
        """
        if self.max_retries <= 0:
            raise PoetryDBAPIError(
                "Unreachable state in PoetryDB client backoff routine."
            )

        for attempt in range(self.max_retries):
            try:
                response = request_fn()

                # Handle Rate Limiting (HTTP 429)
                if response.status_code == 429:
                    retry_after_str = response.headers.get("Retry-After", "60")
                    try:
                        retry_after = int(retry_after_str)
                    except ValueError:
                        retry_after = 60
                    logger.warning(
                        f"Rate limited by PoetryDB."
                        f" Retry-After requested: {retry_after}s"
                    )
                    raise PoetryDBRateLimitError(retry_after)

                response.raise_for_status()
                return response

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    raise
                raise PoetryDBAPIError(
                    f"HTTP Error {exc.response.status_code}: {exc.response.text}"
                ) from exc

            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                if attempt == self.max_retries - 1:
                    raise PoetryDBNetworkError(
                        f"Connection failed after {self.max_retries} attempts"
                    ) from exc

                sleep_time = (2**attempt) + random.uniform(0.1, 1.0)
                logger.warning(
                    f"Transient network issue (attempt {attempt + 1}). "
                    f"Retrying in {sleep_time:.2f} seconds..."
                )
                time.sleep(sleep_time)

        raise PoetryDBAPIError("Unreachable state in PoetryDB client backoff routine.")

    def fetch_text_corpus(self) -> str:
        """
        Fetches raw text content of a random classic poem.

        If a specific author is configured, fetches a random poem by that author
        using a two-step process:
        1. Fetch all poem titles: `/author/{author}/title`
        2. Pick a random title, URL-encode the parameters, and fetch the
           full poem: ``/author,title/{author};{title}``

        If no author is specified, chooses a random author from the
        DEFAULT_CLASSIC_POETS list
        and follows the two-step process.

        If author is "any", queries `/random/1` to retrieve a random poem globally.

        Returns:
            A string containing the lines of the poem joined by newlines.
        """
        # Determine which author to query
        resolved_author = self.author
        if resolved_author is None or resolved_author == "random":
            resolved_author = random.choice(DEFAULT_CLASSIC_POETS)
        elif isinstance(resolved_author, list):
            if len(resolved_author) == 0:
                raise PoetryDBAPIError("Author list cannot be empty.")
            resolved_author = random.choice(resolved_author)

        # Handle global random query
        if resolved_author == "any":

            def make_global_request() -> httpx.Response:
                return self.client.get("/random/1")

            response = self._execute_with_backoff(make_global_request)
            data = response.json()
            if isinstance(data, dict) and "status" in data:
                raise PoetryDBAPIError(
                    f"API Error {data['status']}: {data.get('reason')}"
                )
            if not isinstance(data, list) or len(data) == 0:
                raise PoetryDBAPIError("Unexpected empty response from PoetryDB.")

            poem = data[0]
            lines = poem.get("lines")
            if not isinstance(lines, list):
                raise PoetryDBAPIError("Poem format is invalid: missing 'lines'.")
            return "\n".join(lines)

        else:
            # Two-step retrieval to prevent timeouts on large payloads
            quoted_author = urllib.parse.quote(resolved_author)

            # Step 1: Fetch titles for selected author
            def make_titles_request() -> httpx.Response:
                return self.client.get(f"/author/{quoted_author}/title")

            response = self._execute_with_backoff(make_titles_request)
            data = response.json()
            if isinstance(data, dict) and "status" in data:
                raise PoetryDBAPIError(
                    f"API Error {data['status']}: {data.get('reason')}"
                    f" (author: {resolved_author})"
                )
            if not isinstance(data, list) or len(data) == 0:
                raise PoetryDBAPIError(f"No poems found for author: {resolved_author}")

            # Pick a random title
            selected_item = random.choice(data)
            title = selected_item.get("title")
            if not title:
                raise PoetryDBAPIError("Poem title entry is missing 'title' field.")

            # Step 2: Fetch the full poem using author and title
            quoted_title = urllib.parse.quote(title)

            def make_poem_request() -> httpx.Response:
                # separator must be a literal ';'
                return self.client.get(f"/author,title/{quoted_author};{quoted_title}")

            response = self._execute_with_backoff(make_poem_request)
            poem_data = response.json()
            if isinstance(poem_data, dict) and "status" in poem_data:
                raise PoetryDBAPIError(
                    f"API Error {poem_data['status']}: {poem_data.get('reason')}"
                )
            if not isinstance(poem_data, list) or len(poem_data) == 0:
                raise PoetryDBAPIError(
                    "Unexpected empty response when fetching full poem."
                )

            poem = poem_data[0]
            lines = poem.get("lines")
            if not isinstance(lines, list):
                raise PoetryDBAPIError("Poem format is invalid: missing 'lines'.")
            return "\n".join(lines)

    def close(self) -> None:
        """Cleanly close the underlying HTTPX connection pool."""
        self.client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
