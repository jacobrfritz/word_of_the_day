from unittest.mock import MagicMock, patch

import httpx
import pytest

from word_of_the_day.connectors import (
    Connector,
    SubstackAPIError,
    SubstackClient,
    SubstackNetworkError,
    SubstackRateLimitError,
)


def test_substack_client_implements_protocol() -> None:
    """Verifies that SubstackClient satisfies the Connector protocol."""
    assert issubclass(SubstackClient, Connector)

    client = SubstackClient()
    assert isinstance(client, Connector)
    client.close()


def test_substack_client_initialization() -> None:
    """Verifies initialization logic and parameter parsing."""
    # Default initialization
    client = SubstackClient()
    assert client.category == "philosophy"
    assert client.limit_publications == 3
    assert client.limit_posts_per_pub == 3
    assert str(client.client.base_url) == "https://substack.com"
    client.close()

    # Custom initialization
    client_custom = SubstackClient(
        category="politics",
        limit_publications=5,
        limit_posts_per_pub=2,
        timeout=5.0,
        max_retries=2,
    )
    assert client_custom.category == "politics"
    assert client_custom.limit_publications == 5
    assert client_custom.limit_posts_per_pub == 2
    assert client_custom.max_retries == 2
    client_custom.close()


def test_resolve_category_id_numeric() -> None:
    """Verifies _resolve_category_id returns int directly for numeric strings."""
    client = SubstackClient(category="114")
    assert client._resolve_category_id() == 114
    client.close()


def test_resolve_category_id_slug() -> None:
    """Verifies _resolve_category_id fetches and matches slug correctly."""
    client = SubstackClient(category="philosophy")

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"id": 96, "slug": "culture"},
        {"id": 114, "slug": "philosophy"},
    ]
    client.client.get = MagicMock(return_value=mock_resp)  # type: ignore[method-assign]

    assert client._resolve_category_id() == 114
    client.client.get.assert_called_once_with("/api/v1/categories")
    client.close()


def test_resolve_category_id_not_found() -> None:
    """Verifies _resolve_category_id raises error if slug is not found."""
    client = SubstackClient(category="nonexistent")

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"id": 96, "slug": "culture"}]
    client.client.get = MagicMock(return_value=mock_resp)  # type: ignore[method-assign]

    with pytest.raises(SubstackAPIError) as excinfo:
        client._resolve_category_id()

    assert "nonexistent" in str(excinfo.value)
    client.close()


def test_discover_substack_feeds_success() -> None:
    """Verifies that discover_substack_feeds parses the trending API correctly."""
    client = SubstackClient(category="philosophy")

    def mock_get(
        url: str, *args: list[float], **kwargs: dict[str, float]
    ) -> httpx.Response:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        if url == "/api/v1/categories":
            mock_resp.json.return_value = [{"id": 114, "slug": "philosophy"}]
        elif url == "/api/v1/category/public/114/trending":
            mock_resp.json.return_value = {
                "publications": [
                    {"base_url": "https://pub1.substack.com"},
                    {"base_url": "https://pub2.substack.com/"},
                    {"base_url": None},
                    "not-a-dict",
                ]
            }
        else:
            mock_resp.status_code = 404
        return mock_resp

    client.client.get = MagicMock(side_effect=mock_get)  # type: ignore[method-assign]

    feeds = client.discover_substack_feeds()

    assert feeds == [
        "https://pub1.substack.com/feed",
        "https://pub2.substack.com/feed",
    ]
    assert client.client.get.call_count == 2
    client.close()


def test_discover_substack_feeds_error() -> None:
    """Verifies discover_substack_feeds raises SubstackAPIError on fetch failure."""
    client = SubstackClient(category="114")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        message="500 Error",
        request=MagicMock(),
        response=mock_response,
    )

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    with pytest.raises(SubstackAPIError) as excinfo:
        client.discover_substack_feeds()

    assert "HTTP Error 500" in str(excinfo.value)
    client.close()


def test_fetch_rss_feed_content_success() -> None:
    """Verifies fetch_rss_feed_content successfully fetches and parses RSS feeds."""
    client = SubstackClient(limit_posts_per_pub=2)

    rss_xml = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
        <channel>
            <title>My Substack</title>
            <item>
                <title>First Post</title>
                <description><![CDATA[<p>First desc.</p>]]></description>
            </item>
            <item>
                <title>Second Post</title>
                <description>This has no HTML tags</description>
            </item>
            <item>
                <title>Third Post</title>
                <description>Should be ignored due to limit</description>
            </item>
        </channel>
    </rss>
    """

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.content = rss_xml.encode("utf-8")

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    content = client.fetch_rss_feed_content("https://test.substack.com/feed")

    expected_content = "First Post - First desc.\n\nSecond Post - This has no HTML tags"
    assert content == expected_content
    client.client.get.assert_called_once_with("https://test.substack.com/feed")
    client.close()


def test_fetch_rss_feed_content_namespaces() -> None:
    """Verifies RSS feed parsing works when elements use XML namespaces."""
    client = SubstackClient(limit_posts_per_pub=1)

    rss_xml = """<?xml version="1.0" encoding="utf-8"?>
    <rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">
        <channel>
            <item>
                <title>Namespace Post</title>
                <description>Namespace description</description>
                <content:encoded><![CDATA[<p>Full content</p>]]></content:encoded>
            </item>
        </channel>
    </rss>
    """

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.content = rss_xml.encode("utf-8")

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    content = client.fetch_rss_feed_content("https://test.substack.com/feed")
    assert content == "Namespace Post - Namespace description"
    client.close()


def test_fetch_rss_feed_content_xml_error() -> None:
    """Verifies fetch_rss_feed_content raises SubstackAPIError on invalid XML."""
    client = SubstackClient()

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.content = b"invalid xml"

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    with pytest.raises(SubstackAPIError) as excinfo:
        client.fetch_rss_feed_content("https://test.substack.com/feed")

    assert "Error parsing RSS XML" in str(excinfo.value)
    client.close()


def test_fetch_text_corpus_success() -> None:
    """Verifies fetch_text_corpus discovers and aggregates feeds correctly."""
    client = SubstackClient(
        category="philosophy", limit_publications=2, limit_posts_per_pub=1
    )

    # Mock discover_substack_feeds to return two feeds
    client.discover_substack_feeds = MagicMock(  # type: ignore[method-assign]
        return_value=[
            "https://pub1.substack.com/feed",
            "https://pub2.substack.com/feed",
        ]
    )

    # Mock fetch_rss_feed_content for both feeds
    def mock_fetch_rss(url: str) -> str:
        if "pub1" in url:
            return "Pub One Post - Body One"
        elif "pub2" in url:
            return "Pub Two Post - Body Two"
        return ""

    client.fetch_rss_feed_content = MagicMock(side_effect=mock_fetch_rss)  # type: ignore[method-assign]

    corpus = client.fetch_text_corpus()

    expected_corpus = (
        "Pub One Post - Body One\n\n"
        "=== NEW PUBLICATION FEED ===\n\n"
        "Pub Two Post - Body Two"
    )
    assert corpus == expected_corpus
    client.discover_substack_feeds.assert_called_once()
    assert client.fetch_rss_feed_content.call_count == 2
    client.close()


def test_fetch_text_corpus_one_fails() -> None:
    """Verifies fetch_text_corpus continues even if one publication feed fails."""
    client = SubstackClient(
        category="philosophy", limit_publications=2, limit_posts_per_pub=1
    )

    client.discover_substack_feeds = MagicMock(  # type: ignore[method-assign]
        return_value=[
            "https://pub1.substack.com/feed",
            "https://pub2.substack.com/feed",
        ]
    )

    def mock_fetch_rss(url: str) -> str:
        if "pub1" in url:
            raise SubstackAPIError("Mocked network failure")
        elif "pub2" in url:
            return "Pub Two Post - Body Two"
        return ""

    client.fetch_rss_feed_content = MagicMock(side_effect=mock_fetch_rss)  # type: ignore[method-assign]

    corpus = client.fetch_text_corpus()

    assert corpus == "Pub Two Post - Body Two"
    client.close()


def test_fetch_text_corpus_all_fails() -> None:
    """Verifies fetch_text_corpus raises SubstackAPIError if all feeds fail."""
    client = SubstackClient(category="philosophy", limit_publications=2)

    client.discover_substack_feeds = MagicMock(  # type: ignore[method-assign]
        return_value=["https://pub1.substack.com/feed"]
    )
    client.fetch_rss_feed_content = MagicMock(  # type: ignore[method-assign]
        side_effect=SubstackAPIError("All failed")
    )

    with pytest.raises(SubstackAPIError) as excinfo:
        client.fetch_text_corpus()

    assert "Failed to retrieve any content" in str(excinfo.value)
    client.close()


def test_execute_with_backoff_rate_limit() -> None:
    """Verifies _execute_with_backoff correctly handles rate limits (HTTP 429)."""
    client = SubstackClient()

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "45"}

    request_fn = MagicMock(return_value=mock_response)

    with pytest.raises(SubstackRateLimitError) as excinfo:
        client._execute_with_backoff(request_fn)

    assert excinfo.value.retry_after == 45
    assert "Please retry after 45 seconds" in str(excinfo.value)
    request_fn.assert_called_once()
    client.close()


@patch("time.sleep", return_value=None)
def test_execute_with_backoff_transient_retry(mock_sleep: MagicMock) -> None:
    """Verifies _execute_with_backoff retries on network error before raising."""
    client = SubstackClient(max_retries=3)

    request_fn = MagicMock(
        side_effect=httpx.NetworkError("Transient connection failed")
    )

    with pytest.raises(SubstackNetworkError) as excinfo:
        client._execute_with_backoff(request_fn)

    assert "Connection failed after 3 attempts" in str(excinfo.value)
    assert request_fn.call_count == 3
    assert mock_sleep.call_count == 2
    client.close()
