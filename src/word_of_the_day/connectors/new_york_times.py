import calendar
import datetime
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


class NewYorkTimesAPIError(Exception):
    """Base exception for all New York Times API client errors."""

    pass


class NewYorkTimesRateLimitError(NewYorkTimesAPIError):
    """Raised when the client is rate-limited (HTTP 429) by the New York Times API."""

    def __init__(self, retry_after: int = 60, message: str = "Rate limit exceeded"):
        self.retry_after = retry_after
        super().__init__(f"{message}. Please retry after {retry_after} seconds.")


class NewYorkTimesNetworkError(NewYorkTimesAPIError):
    """Raised when a physical network error or timeout occurs."""

    pass


class NewYorkTimesClient(Connector):
    """
    A robust client for fetching text corpora from the New York Times
    Article Search API.
    """

    BASE_URL = "https://api.nytimes.com"

    def __init__(
        self,
        api_key: str,
        timeout: float = 10.0,
        max_retries: int = 3,
        start_year: int = 1851,
        end_year: int | None = None,
    ):
        """
        Initialize the New York Times Client.

        Args:
            api_key: The developer API key for the New York Times API.
            timeout: Network timeout in seconds.
            max_retries: Number of attempts for transient errors or empty
                         searches before failing.
            start_year: The earliest year to consider for random publication searches.
            end_year: The latest year to consider (defaults to the current year).
        """
        if not api_key:
            raise NewYorkTimesAPIError("API key must be a non-empty string.")

        self.api_key = api_key
        self.max_retries = max_retries
        self.start_year = start_year
        self.end_year = end_year if end_year is not None else datetime.date.today().year

        if self.start_year > self.end_year:
            raise NewYorkTimesAPIError("start_year cannot be greater than end_year.")

        headers = {
            "Accept": "application/json; charset=utf-8",
            "Accept-Encoding": "gzip",
        }

        self.client = httpx.Client(
            base_url=self.BASE_URL,
            headers=headers,
            timeout=httpx.Timeout(timeout),
            http2=True,
            follow_redirects=True,
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
                    # NYT API documentation notes a rate limit. Sometimes a
                    # Retry-After header is provided, otherwise we default
                    # to a standard 60-second backoff.
                    retry_after_str = response.headers.get("Retry-After", "60")
                    try:
                        retry_after = int(retry_after_str)
                    except ValueError:
                        retry_after = 60

                    logger.warning(
                        "Rate limited by New York Times API. Retry-After requested: "
                        f"{retry_after}s"
                    )
                    raise NewYorkTimesRateLimitError(retry_after)

                # Raise other HTTP status exceptions (4xx, 5xx)
                response.raise_for_status()
                return response

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    raise
                raise NewYorkTimesAPIError(
                    f"HTTP Error {exc.response.status_code}: {exc.response.text}"
                ) from exc

            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                # Transient network error: calculate exponential backoff with jitter
                if attempt == self.max_retries - 1:
                    raise NewYorkTimesNetworkError(
                        f"Connection failed after {self.max_retries} attempts"
                    ) from exc

                sleep_time = (2**attempt) + random.uniform(0.1, 1.0)
                logger.warning(
                    "Transient connection issue. Retrying in "
                    f"{sleep_time:.2f} seconds..."
                )
                time.sleep(sleep_time)

        raise NewYorkTimesAPIError("Unreachable state in client backoff routine.")

    def fetch_text_corpus(self) -> str:
        """
        Fetches text content from a random New York Times article matching
        a randomly picked publication year, month, and search page number.

        Returns:
            A string containing the text of a random NYT article
            (abstract/lead paragraph).
        """
        # We allow up to 5 attempts to find a random month/year/page
        # that yields articles
        max_search_attempts = 5

        for attempt in range(max_search_attempts):
            year = random.randint(self.start_year, self.end_year)
            month = random.randint(1, 12)
            # page 0-2 ensures we stay within result bounds for most queries
            page = random.randint(0, 2)

            # Calculate the last day of the selected month
            last_day = calendar.monthrange(year, month)[1]
            begin_date = f"{year}{month:02d}01"
            end_date = f"{year}{month:02d}{last_day:02d}"

            logger.info(
                f"NYT fetch attempt {attempt + 1}/{max_search_attempts}: "
                f"Querying begin_date={begin_date}, end_date={end_date}, page={page}"
            )

            params: dict[str, str | int | float | bool | None] = {
                "begin_date": begin_date,
                "end_date": end_date,
                "page": page,
                "api-key": self.api_key,
            }

            try:

                def make_request(
                    p: dict[str, str | int | float | bool | None] = params,
                ) -> httpx.Response:
                    return self.client.get(
                        "/svc/search/v2/articlesearch.json", params=p
                    )

                response = self._execute_with_backoff(make_request)
                data = response.json()

                docs = data.get("response", {}).get("docs", [])
                if not docs:
                    logger.warning(
                        f"No articles returned for begin_date={begin_date}, "
                        f"end_date={end_date}, page={page}. "
                        "Trying another random combination."
                    )
                    continue

                # Shuffle docs to pick one randomly
                shuffled_docs = list(docs)
                random.shuffle(shuffled_docs)

                for doc in shuffled_docs:
                    # Pull lead_paragraph, falling back to abstract, then snippet
                    text = (
                        doc.get("lead_paragraph")
                        or doc.get("abstract")
                        or doc.get("snippet")
                    )
                    if isinstance(text, str) and text.strip():
                        logger.info(
                            f"Successfully retrieved article text (length={len(text)}) "
                            f"from begin_date={begin_date}, end_date={end_date}."
                        )
                        return text.strip()

                logger.warning(
                    "Articles found, but none contained valid text. "
                    "Trying another random combination."
                )

            except NewYorkTimesAPIError:
                # Re-raise NYT API errors (including network, rate limit, etc.)
                # immediately
                raise
            except Exception as exc:
                # If we hit other unexpected errors (e.g. JSON parsing errors),
                # we log and retry
                logger.warning(f"Error during search attempt {attempt + 1}: {exc}")
                if attempt == max_search_attempts - 1:
                    raise NewYorkTimesAPIError(
                        f"Failed to fetch text corpus after "
                        f"{max_search_attempts} attempts: {exc}"
                    ) from exc

        raise NewYorkTimesAPIError(
            f"Failed to fetch text corpus after {max_search_attempts} attempts: "
            "no valid article text found."
        )

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
