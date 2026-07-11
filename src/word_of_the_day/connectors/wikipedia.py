import logging
import os
import random
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any, Self

import httpx

from .protocol import Connector

# Configure module logging
logger = logging.getLogger(__name__)


class WikipediaAPIError(Exception):
    """Base exception for all Wikipedia API client errors."""

    pass


class WikipediaRateLimitError(WikipediaAPIError):
    """Raised when the client is rate-limited (HTTP 429) by Wikipedia."""

    def __init__(self, retry_after: int, message: str = "Rate limit exceeded"):
        self.retry_after = retry_after
        super().__init__(f"{message}. Please retry after {retry_after} seconds.")


class WikipediaNetworkError(WikipediaAPIError):
    """Raised when a physical network error or timeout occurs."""

    pass


class WikipediaClient(Connector):
    """
    A highly robust and compliant Wikipedia API Client using HTTPX.

    Adheres strictly to the Wikimedia Foundation API Usage Guidelines,
    providing compliant User-Agents, handling 429 Rate Limits, and
    supporting both REST summaries and full-text extraction.
    """

    # Using the base domain allows us to query both REST and Action API
    # endpoints cleanly
    BASE_URL = "https://en.wikipedia.org"

    def __init__(
        self,
        app_name: str,
        contact_email: str,
        version: str = "1.0",
        timeout: float = 10.0,
        max_retries: int = 3,
    ):
        """
        Initialize the Wikipedia Client.

        Args:
            app_name: Name of your application (e.g. 'WordOfTheDay').
            contact_email: Contact email used in the User-Agent header as required
                           by Wikipedia's API etiquette policy.
            version: Version number of your application.
            timeout: Network timeout in seconds.
            max_retries: Number of attempts for transient errors before failing.
        """
        self.max_retries = max_retries

        # Build Wikimedia-compliant User-Agent header
        # Syntax: <App_Name>/<Version> (<Contact_Details>) <Library_Identifier>
        user_agent = (
            f"{app_name}/{version} (contact: {contact_email}) httpx/{httpx.__version__}"
        )

        headers = {
            "User-Agent": user_agent,
            "Accept": "application/json; charset=utf-8",
            "Accept-Encoding": "gzip",  # Request compressed content to save bandwidth
        }

        # Initialize an HTTPX Client with HTTP/2 and redirect-following enabled.
        # This is required because Wikipedia's random endpoint sends a 303 redirect.
        self.client = httpx.Client(
            base_url=os.environ.get("WIKIPEDIA_BASE_URL", self.BASE_URL),
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
                    # Wikipedia provides a 'Retry-After' header indicating
                    # wait time in seconds
                    retry_after_str = response.headers.get("Retry-After", "60")
                    try:
                        retry_after = int(retry_after_str)
                    except ValueError:
                        retry_after = 60

                    logger.warning(
                        "Rate limited by Wikipedia. Retry-After requested: "
                        f"{retry_after}s"
                    )
                    raise WikipediaRateLimitError(retry_after)

                # Raise other HTTP status exceptions (4xx, 5xx)
                response.raise_for_status()
                return response

            except httpx.HTTPStatusError as exc:
                # If we've already handled 429, handle other HTTP statuses
                if exc.response.status_code == 429:
                    raise
                raise WikipediaAPIError(
                    f"HTTP Error {exc.response.status_code}: {exc.response.text}"
                ) from exc

            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                # Transient network error: calculate exponential backoff with jitter
                if attempt == self.max_retries - 1:
                    raise WikipediaNetworkError(
                        f"Connection failed after {self.max_retries} attempts"
                    ) from exc

                sleep_time = (2**attempt) + random.uniform(0.1, 1.0)
                logger.warning(
                    "Transient connection issue. Retrying in "
                    f"{sleep_time:.2f} seconds..."
                )
                time.sleep(sleep_time)

        raise WikipediaAPIError("Unreachable state in client backoff routine.")

    def get_random_article_summary(self) -> dict[str, Any]:
        """
        Fetches a random Wikipedia article's summary, title, and URL in a
        single high-performance REST API call.

        Returns:
            A dictionary containing:
                - 'title': The clean article title.
                - 'summary': The plain-text intro abstract.
                - 'url': The desktop browser landing URL.
                - 'thumbnail': Optional main image URL (None if unavailable).
        """

        def make_request() -> httpx.Response:
            # REST endpoint for a random article summary
            return self.client.get("/api/rest_v1/page/random/summary")

        response = self._execute_with_backoff(make_request)
        data = response.json()

        # Safely parse structural metadata out of the REST response
        return {
            "title": data.get("title", "Untitled"),
            "summary": data.get("extract", "No summary text available."),
            "url": data.get("content_urls", {})
            .get("desktop", {})
            .get("page", "https://en.wikipedia.org"),
            "thumbnail": data.get("thumbnail", {}).get("source"),
        }

    def get_article_full_text(self, title: str) -> str:
        """
        Fetches the complete full text of a Wikipedia article using the Action API.
        Automatically strips HTML formatting to return clean plain text.

        Args:
            title: The title of the article to retrieve.

        Returns:
            A string containing the entire plain-text article content.
        """
        params: dict[str, str | int | float | bool | None] = {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "explaintext": True,  # Ask Wikipedia to parse and return clean plain text
            "titles": title,
        }

        def make_request() -> httpx.Response:
            return self.client.get("/w/api.php", params=params)

        response = self._execute_with_backoff(make_request)
        data = response.json()

        # Parse the nested page structure of the Action API response
        pages = data.get("query", {}).get("pages", {})
        if not pages:
            raise WikipediaAPIError("No pages found in Wikipedia response structure.")

        # Get the first page ID (usually the only one returned)
        page_id = next(iter(pages))
        page_data = pages[page_id]

        if "missing" in page_data:
            raise WikipediaAPIError(
                f"Article titled '{title}' does not exist on Wikipedia."
            )

        extract = page_data.get("extract", "No content text available.")
        return extract if isinstance(extract, str) else "No content text available."

    def fetch_text_corpus(self) -> str:
        """
        Fetches raw text content from a random Wikipedia article.

        Returns:
            A string containing the full text of a random Wikipedia article.
        """
        summary = self.get_random_article_summary()
        title = summary["title"]
        return self.get_article_full_text(title)

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


# Example Usage showing Context Management
if __name__ == "__main__":  # pragma: no cover
    # Standard setup using your app credentials
    app_info: dict[str, Any] = {
        "app_name": "WordOfTheDayApp",
        "contact_email": "fritz@example.com",
        "version": "1.0.0",
    }

    print("Initializing robust Wikipedia API connection...")
    try:
        with WikipediaClient(**app_info) as wiki:
            # 1. Fetch random summary/metadata to get a valid title
            print("Fetching a random article summary metadata...")
            article = wiki.get_random_article_summary()
            title = article["title"]

            print(f"\nRandom Article Found: '{title}'")
            print(f"Summary URL:          {article['url']}")
            print("-" * 50)

            # 2. Fetch the entire article body
            print(f"Downloading FULL text content for '{title}'...")
            full_text = wiki.get_article_full_text(title)

            print("\n--- [SUCCESSFULLY DOWNLOADED FULL TEXT] ---")
            # Print the first 1500 characters of the full body as an example
            print(full_text[:1500])
            if len(full_text) > 1500:
                print(
                    "\n... [Truncated "
                    f"{len(full_text) - 1500} "
                    "remaining characters of the article] ..."
                )
            print("-" * 50)

    except WikipediaRateLimitError as e:
        print(f"\n[Rate Limit] Caught active throttling: {e}")
    except WikipediaAPIError as e:
        print(f"\n[API Error] {e}")
