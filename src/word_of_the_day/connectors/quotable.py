import logging
import random
import time
from collections.abc import Callable
from types import TracebackType
from typing import Self

import httpx

from .protocol import Connector

# Configure module logging
logger = logging.getLogger(__name__)


class QuotableAPIError(Exception):
    """Base exception for all Quotable API client errors."""

    pass


class QuotableRateLimitError(QuotableAPIError):
    """Raised when the client is rate-limited (HTTP 429) by the Quotable API."""

    def __init__(self, retry_after: int, message: str = "Rate limit exceeded"):
        self.retry_after = retry_after
        super().__init__(f"{message}. Please retry after {retry_after} seconds.")


class QuotableNetworkError(QuotableAPIError):
    """Raised when a physical network error or timeout occurs."""

    pass


class QuotableClient(Connector):
    """
    A robust client for fetching quotes from the Quotable API.
    """

    BASE_URL = "https://api.quotable.io"

    def __init__(
        self,
        tags: list[str] | str | None = None,
        quotes_per_fetch: int = 20,
        base_url: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
    ):
        """
        Initialize the Quotable Client.

        Args:
            tags: Filter quotes by tags. Can be a list of strings or a single string.
                  If a list, it will be joined using OR logic ('|').
            quotes_per_fetch: The number of quotes to request per fetch.
            base_url: Optional override for the base API URL.
            timeout: Network timeout in seconds.
            max_retries: Number of retry attempts for transient errors.
        """
        self.max_retries = max_retries
        self.quotes_per_fetch = quotes_per_fetch
        self.tags = tags

        resolved_base_url = base_url or self.BASE_URL

        headers = {
            "Accept": "application/json; charset=utf-8",
            "Accept-Encoding": "gzip",
        }

        self.client = httpx.Client(
            base_url=resolved_base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout),
            http2=True,
            follow_redirects=True,
            # api.quotable.io SSL cert is expired; safe for this public read-only API
            verify=False,
        )

    def _execute_with_backoff(
        self, request_fn: Callable[[], httpx.Response]
    ) -> httpx.Response:
        """
        Executes a network request using exponential backoff with jitter
        to mitigate transient network errors, and handles rate limiting.
        """
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
                        "Rate limited by Quotable API. Retry-After requested: "
                        f"{retry_after}s"
                    )
                    raise QuotableRateLimitError(retry_after)

                # Raise other HTTP status exceptions (4xx, 5xx)
                response.raise_for_status()
                return response

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    raise
                raise QuotableAPIError(
                    f"HTTP Error {exc.response.status_code}: {exc.response.text}"
                ) from exc

            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                # Transient network error: calculate exponential backoff with jitter
                if attempt == self.max_retries - 1:
                    raise QuotableNetworkError(
                        f"Connection failed after {self.max_retries} attempts"
                    ) from exc

                sleep_time = (2**attempt) + random.uniform(0.1, 1.0)
                logger.warning(
                    "Transient connection issue. Retrying in "
                    f"{sleep_time:.2f} seconds..."
                )
                time.sleep(sleep_time)

        raise QuotableAPIError("Unreachable state in client backoff routine.")

    def fetch_text_corpus(self) -> str:
        """
        Fetches a random selection of quotes and joins them as a corpus.

        Returns:
            A string containing the formatted quotes joined by double newlines.
        """
        params: dict[str, str | int | float | bool | None] = {}

        # Build tag parameters
        if self.tags:
            if isinstance(self.tags, list):
                # We use pipe | for OR matching as it is more likely to yield results
                # than comma-separated AND matching.
                params["tags"] = "|".join(self.tags)
            else:
                params["tags"] = self.tags

        # Limit the number of quotes requested
        if self.quotes_per_fetch > 0:
            params["limit"] = self.quotes_per_fetch

        def make_request() -> httpx.Response:
            return self.client.get("/quotes/random", params=params)

        try:
            response = self._execute_with_backoff(make_request)
            data = response.json()
        except Exception as exc:
            if isinstance(exc, QuotableAPIError):
                raise
            raise QuotableAPIError(
                f"Error communicating with Quotable API: {exc}"
            ) from exc

        # The random endpoint returns an array of quote objects.
        # But handle a dictionary just in case it returns a single object.
        quotes = data if isinstance(data, list) else [data]

        if not quotes:
            raise QuotableAPIError("No quotes returned from Quotable API.")

        formatted_quotes = []
        for quote in quotes:
            if not isinstance(quote, dict):
                continue
            content = quote.get("content")
            author = quote.get("author", "Unknown")
            if content and isinstance(content, str):
                formatted_quotes.append(f"{content.strip()} -- {author.strip()}")

        if not formatted_quotes:
            raise QuotableAPIError("Quotes found, but none contained valid text.")

        return "\n\n".join(formatted_quotes)

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
