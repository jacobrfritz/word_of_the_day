import html
import logging
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from types import TracebackType
from typing import Self

import httpx

from .protocol import Connector

# Configure module logging
logger = logging.getLogger(__name__)


class SubstackAPIError(Exception):
    """Base exception for all Substack API client errors."""

    pass


class SubstackRateLimitError(SubstackAPIError):
    """Raised when the client is rate-limited (HTTP 429) by Substack."""

    def __init__(self, retry_after: int, message: str = "Rate limit exceeded"):
        self.retry_after = retry_after
        super().__init__(f"{message}. Please retry after {retry_after} seconds.")


class SubstackNetworkError(SubstackAPIError):
    """Raised when a network error or timeout occurs."""

    pass


class SubstackClient(Connector):
    """
    A connector for fetching a text corpus from Substack trending publications.
    """

    BASE_URL = "https://substack.com"

    def connector_name(self) -> str:
        return "substack"

    def __init__(
        self,
        category: str = "philosophy",
        limit_publications: int = 3,
        limit_posts_per_pub: int = 3,
        timeout: float = 10.0,
        max_retries: int = 3,
        shuffle_publications: bool = True,
    ) -> None:
        """
        Initialize the Substack Client.

        Args:
            category: The category slug or ID of trending posts to discover.
            limit_publications: Maximum number of publications to fetch.
            limit_posts_per_pub: Maximum number of posts to parse per publication.
            timeout: Network timeout in seconds.
            max_retries: Number of retry attempts for transient errors.
            shuffle_publications: Whether to randomly shuffle publications.
        """
        self.category = category
        self.limit_publications = limit_publications
        self.limit_posts_per_pub = limit_posts_per_pub
        self.max_retries = max_retries
        self.shuffle_publications = shuffle_publications

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Accept": "application/json, application/xml, text/xml, */*",
        }

        # Do not use http2=True to avoid potential Cloudflare challenge triggers
        self.client = httpx.Client(
            base_url=os.environ.get("SUBSTACK_BASE_URL", self.BASE_URL),
            headers=headers,
            timeout=httpx.Timeout(timeout),
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
                    retry_after_str = response.headers.get("Retry-After", "60")
                    try:
                        retry_after = int(retry_after_str)
                    except ValueError:
                        retry_after = 60

                    logger.warning(
                        f"Rate limited by Substack API. Retry-After requested: "
                        f"{retry_after}s"
                    )
                    raise SubstackRateLimitError(retry_after)

                # Raise other HTTP status exceptions (4xx, 5xx)
                response.raise_for_status()
                return response

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    raise
                raise SubstackAPIError(
                    f"HTTP Error {exc.response.status_code}: {exc.response.text[:500]}"
                ) from exc

            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                # Transient network error: calculate exponential backoff with jitter
                if attempt == self.max_retries - 1:
                    raise SubstackNetworkError(
                        f"Connection failed after {self.max_retries} attempts"
                    ) from exc

                sleep_time = (2**attempt) + random.uniform(0.1, 1.0)
                logger.warning(
                    f"Transient connection issue. Retrying in "
                    f"{sleep_time:.2f} seconds..."
                )
                time.sleep(sleep_time)

        raise SubstackAPIError("Unreachable state in client backoff routine.")

    def _resolve_category_id(self) -> int:
        """
        Resolves the configured category name/slug or string ID into an integer ID.

        Returns:
            An integer category ID.
        """
        if self.category.isdigit():
            return int(self.category)

        url = "/api/v1/categories"

        def make_request() -> httpx.Response:
            return self.client.get(url)

        try:
            response = self._execute_with_backoff(make_request)
            data = response.json()
        except Exception as exc:
            if isinstance(exc, SubstackAPIError):
                raise
            raise SubstackAPIError(f"Failed to fetch category list: {exc}") from exc

        target_slug = self.category.strip().lower()
        if isinstance(data, list):
            for category_dict in data:
                if not isinstance(category_dict, dict):
                    continue
                slug = category_dict.get("slug")
                if slug and slug.strip().lower() == target_slug:
                    cat_id = category_dict.get("id")
                    if isinstance(cat_id, int):
                        return cat_id
                    elif isinstance(cat_id, str) and cat_id.isdigit():
                        return int(cat_id)
                    else:
                        raise SubstackAPIError(
                            f"Resolved category '{self.category}' but ID "
                            f"is non-integer: {cat_id}"
                        )

        raise SubstackAPIError(f"Category '{self.category}' not found on Substack.")

    def discover_substack_feeds(self) -> list[str]:
        """
        Pulls trending publications for the configured category from Substack's
        public API and returns their RSS feed URLs.

        Returns:
            A list of unique RSS feed URLs.
        """
        try:
            category_id = self._resolve_category_id()
        except Exception as exc:
            raise SubstackAPIError(f"Failed to resolve category ID: {exc}") from exc

        url = f"/api/v1/category/public/{category_id}/trending"

        def make_request() -> httpx.Response:
            return self.client.get(url)

        try:
            response = self._execute_with_backoff(make_request)
            data = response.json()
        except Exception as exc:
            if isinstance(exc, SubstackAPIError):
                raise
            raise SubstackAPIError(
                f"Error communicating with Substack API: {exc}"
            ) from exc

        rss_feeds: list[str] = []
        publications = data.get("publications", []) if isinstance(data, dict) else []
        for pub in publications:
            if not isinstance(pub, dict):
                continue
            pub_url = pub.get("base_url")
            if pub_url and isinstance(pub_url, str):
                rss_feeds.append(f"{pub_url.rstrip('/')}/feed")

        # Return unique set of feeds, maintaining order
        seen = set()
        unique_feeds = []
        for feed in rss_feeds:
            if feed not in seen:
                seen.add(feed)
                unique_feeds.append(feed)

        return unique_feeds

    def fetch_rss_feed_content(self, feed_url: str) -> str:
        """
        Fetches an RSS feed and extracts text content from items.

        Args:
            feed_url: The URL of the RSS feed.

        Returns:
            A string containing the concatenated text of the posts.
        """

        def make_request() -> httpx.Response:
            return self.client.get(feed_url)

        try:
            response = self._execute_with_backoff(make_request)
            xml_content = response.content
        except Exception as exc:
            if isinstance(exc, SubstackAPIError):
                raise
            raise SubstackAPIError(
                f"Error fetching RSS feed {feed_url}: {exc}"
            ) from exc

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as exc:
            raise SubstackAPIError(
                f"Error parsing RSS XML from {feed_url}: {exc}"
            ) from exc

        # Find items robustly ignoring namespaces
        items = []
        for child in root.iter():
            tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag_name == "item":
                items.append(child)

        post_texts: list[str] = []
        for item in items[: self.limit_posts_per_pub]:
            title = ""
            description = ""
            content_encoded = ""
            for child in item:
                tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag_name == "title" and child.text:
                    title = child.text.strip()
                elif tag_name == "description" and child.text:
                    description = child.text.strip()
                elif tag_name == "encoded" and child.text:
                    content_encoded = child.text.strip()

            clean_title = self._clean_text(title)
            clean_description = self._clean_text(description)
            clean_content = self._clean_text(content_encoded)

            parts = []
            if clean_title:
                parts.append(clean_title)
            if clean_description:
                parts.append(clean_description)
            if clean_content:
                parts.append(clean_content)

            if parts:
                post_texts.append(" - ".join(parts))

        return "\n\n".join(post_texts)

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        # Decode HTML entities robustly
        clean = html.unescape(text)
        # Remove HTML tags
        clean = re.sub(r"<[^>]+>", " ", clean)
        # Normalize whitespace (replace tabs, multiple spaces, etc. with a single space)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()

    def fetch_text_corpus(self) -> str:
        """
        Discovers trending Substack feeds for the configured category and
        fetches/combines text content from their latest posts.

        Returns:
            A string containing all fetched text joined by double newlines.
        """
        logger.info(
            f"Discovering trending Substack feeds in category: '{self.category}'"
        )
        try:
            feed_urls = self.discover_substack_feeds()
        except Exception as exc:
            raise SubstackAPIError(f"Substack feed discovery failed: {exc}") from exc

        if not feed_urls:
            raise SubstackAPIError(
                f"No trending feeds discovered for category '{self.category}'"
            )

        # Make a copy of feed_urls so we don't mutate the original discovered order
        feeds_to_use = list(feed_urls)
        if self.shuffle_publications:
            random.shuffle(feeds_to_use)

        selected_feeds = feeds_to_use[: self.limit_publications]
        logger.info(
            f"Fetching RSS content from {len(selected_feeds)} publications "
            f"(out of {len(feed_urls)} discovered)"
        )

        corpora: list[str] = []
        for feed_url in selected_feeds:
            try:
                feed_text = self.fetch_rss_feed_content(feed_url)
                if feed_text:
                    corpora.append(feed_text)
            except Exception as exc:
                logger.error(f"Failed to fetch content from RSS feed {feed_url}: {exc}")
                continue

        if not corpora:
            raise SubstackAPIError(
                "Failed to retrieve any content from any Substack RSS feed."
            )

        return "\n\n=== NEW PUBLICATION FEED ===\n\n".join(corpora)

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
