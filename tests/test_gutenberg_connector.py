import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from word_of_the_day.connectors import (
    Connector,
    GutenbergAPIError,
    GutenbergClient,
    GutenbergNetworkError,
    GutenbergRateLimitError,
)
from word_of_the_day.connectors.gutenberg import DEFAULT_CLASSIC_IDS


def test_gutenberg_client_implements_protocol() -> None:
    """Verifies that GutenbergClient satisfies the Connector protocol."""
    assert issubclass(GutenbergClient, Connector)

    client = GutenbergClient(book_id=2701)
    assert isinstance(client, Connector)
    client.close()


def test_gutenberg_client_initialization() -> None:
    """Verifies initialization logic with default, random, and custom book IDs."""
    # 1. Default (None)
    client_default = GutenbergClient()
    assert client_default.book_id in DEFAULT_CLASSIC_IDS
    assert client_default._is_random_discovery is True

    # 2. String "random"
    client_random = GutenbergClient(book_id="random")
    assert 10 <= client_random.book_id <= 60000
    assert client_random._is_random_discovery is True

    # 3. Custom integer/string integer
    client_custom = GutenbergClient(book_id=123)
    assert client_custom.book_id == 123
    assert client_custom._is_random_discovery is False

    client_custom_str = GutenbergClient(book_id="456")
    assert client_custom_str.book_id == 456
    assert client_custom_str._is_random_discovery is False

    # 4. Invalid ID
    with pytest.raises(GutenbergAPIError) as exc_info:
        GutenbergClient(book_id="invalid")
    assert "Invalid book ID" in str(exc_info.value)


@patch("gutenbergpy.textget.get_text_by_id")
@patch("gutenbergpy.textget.strip_headers")
def test_fetch_text_corpus_success(mock_strip: MagicMock, mock_get: MagicMock) -> None:
    """Verifies successful downloading and cleaning of a Gutenberg book."""
    mock_get.return_value = b"raw compressed book data"
    mock_strip.return_value = b"cleaned book content"

    client = GutenbergClient(book_id=2701)
    text = client.fetch_text_corpus()

    assert text == "cleaned book content"
    mock_get.assert_called_once_with(2701)
    mock_strip.assert_called_once_with(b"raw compressed book data")


@patch("gutenbergpy.textget.get_text_by_id")
def test_rate_limiting(mock_get: MagicMock) -> None:
    """Verifies that 429 HTTP errors raise GutenbergRateLimitError."""
    # Create an HTTPError representing a 429
    url_err = urllib.error.HTTPError(
        url="http://example.com",
        code=429,
        msg="Too Many Requests",
        hdrs=None,  # type: ignore
        fp=None,
    )
    mock_get.side_effect = url_err

    client = GutenbergClient(book_id=2701, max_retries=1)

    with pytest.raises(GutenbergRateLimitError) as exc_info:
        client.fetch_text_corpus()

    assert "Rate limited while downloading Gutenberg book 2701" in str(exc_info.value)


@patch("gutenbergpy.textget.get_text_by_id")
def test_network_error(mock_get: MagicMock) -> None:
    """Verifies that other HTTP/URLErrors raise GutenbergNetworkError."""
    url_err = urllib.error.URLError(reason="Connection refused")
    mock_get.side_effect = url_err

    client = GutenbergClient(book_id=2701, max_retries=1)

    with pytest.raises(GutenbergNetworkError) as exc_info:
        client.fetch_text_corpus()

    assert "Network error while downloading Gutenberg book 2701" in str(exc_info.value)


@patch("gutenbergpy.textget.get_text_by_id")
def test_gutenbergpy_internal_error_specific_id(mock_get: MagicMock) -> None:
    """Verifies that TypeError (caused by raise None bug) for a specific ID
    fails directly."""
    mock_get.side_effect = TypeError("exceptions must derive from BaseException")

    client = GutenbergClient(book_id=2701, max_retries=2)

    with pytest.raises(GutenbergAPIError) as exc_info:
        client.fetch_text_corpus()

    assert "could not be resolved or downloaded by gutenbergpy" in str(exc_info.value)


@patch("gutenbergpy.textget.get_text_by_id")
@patch("gutenbergpy.textget.strip_headers")
def test_gutenbergpy_internal_error_random_discovery(
    mock_strip: MagicMock, mock_get: MagicMock
) -> None:
    """Verifies that TypeError during random discovery retries with another book ID."""
    # First call raises TypeError, second call succeeds
    mock_get.side_effect = [
        TypeError("exceptions must derive from BaseException"),
        b"raw book",
    ]
    mock_strip.return_value = b"success text"

    client = GutenbergClient(book_id=None, max_retries=3)
    text = client.fetch_text_corpus()

    assert text == "success text"
    assert mock_get.call_count == 2


def test_context_manager() -> None:
    """Verifies that GutenbergClient can be used as a context manager."""
    with GutenbergClient(book_id=2701) as client:
        assert isinstance(client, Connector)
