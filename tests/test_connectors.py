from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from word_of_the_day.connectors import (
    Connector,
    WikipediaAPIError,
    WikipediaClient,
    WikipediaNetworkError,
    WikipediaRateLimitError,
)


def test_wikipedia_client_implements_protocol() -> None:
    """Verifies that WikipediaClient satisfies the Connector protocol."""
    assert issubclass(WikipediaClient, Connector)

    client = WikipediaClient(app_name="TestApp", contact_email="test@example.com")
    assert isinstance(client, Connector)
    client.close()


def test_get_random_article_summary_success() -> None:
    """Verifies that get_random_article_summary handles a successful JSON response."""
    client = WikipediaClient(app_name="TestApp", contact_email="test@example.com")

    mock_data = {
        "title": "Python (programming language)",
        "extract": "Python is a high-level programming language.",
        "content_urls": {
            "desktop": {
                "page": "https://en.wikipedia.org/wiki/Python_(programming_language)"
            }
        },
        "thumbnail": {"source": "https://example.com/python.png"},
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data

    client.client.get = MagicMock(return_value=mock_response)

    summary = client.get_random_article_summary()

    assert summary["title"] == "Python (programming language)"
    assert summary["summary"] == "Python is a high-level programming language."
    assert (
        summary["url"] == "https://en.wikipedia.org/wiki/Python_(programming_language)"
    )
    assert summary["thumbnail"] == "https://example.com/python.png"

    client.client.get.assert_called_once_with("/api/rest_v1/page/random/summary")
    client.close()


def test_get_article_full_text_success() -> None:
    """Verifies get_article_full_text retrieves clean plain text."""
    client = WikipediaClient(app_name="TestApp", contact_email="test@example.com")

    mock_data = {
        "query": {
            "pages": {
                "12345": {
                    "pageid": 12345,
                    "title": "Python",
                    "extract": "Full text of Python article.",
                }
            }
        }
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data

    client.client.get = MagicMock(return_value=mock_response)

    full_text = client.get_article_full_text("Python")

    assert full_text == "Full text of Python article."
    client.client.get.assert_called_once()
    client.close()


def test_fetch_text_corpus_success() -> None:
    """Verifies fetch_text_corpus retrieves a random article and returns full text."""
    client = WikipediaClient(app_name="TestApp", contact_email="test@example.com")

    mock_summary_data = {
        "title": "Python",
        "extract": "Python summary.",
        "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Python"}},
    }
    mock_summary_response = MagicMock(spec=httpx.Response)
    mock_summary_response.status_code = 200
    mock_summary_response.json.return_value = mock_summary_data

    mock_text_data = {
        "query": {
            "pages": {
                "12345": {
                    "pageid": 12345,
                    "title": "Python",
                    "extract": "Full text of Python article.",
                }
            }
        }
    }
    mock_text_response = MagicMock(spec=httpx.Response)
    mock_text_response.status_code = 200
    mock_text_response.json.return_value = mock_text_data

    client.client.get = MagicMock(
        side_effect=[mock_summary_response, mock_text_response]
    )

    corpus = client.fetch_text_corpus()

    assert corpus == "Full text of Python article."
    assert client.client.get.call_count == 2
    client.close()


def test_rate_limiting() -> None:
    """Verifies that 429 rate limiting throws a WikipediaRateLimitError."""
    client = WikipediaClient(
        app_name="TestApp", contact_email="test@example.com", max_retries=1
    )

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "10"}

    client.client.get = MagicMock(return_value=mock_response)

    with pytest.raises(WikipediaRateLimitError) as exc_info:
        client.get_random_article_summary()

    assert exc_info.value.retry_after == 10
    assert "Please retry after 10 seconds." in str(exc_info.value)
    client.close()


def test_context_manager() -> None:
    """Verifies that the context manager correctly closes the client."""
    with patch.object(httpx.Client, "close") as mock_close:
        with WikipediaClient(
            app_name="TestApp", contact_email="test@example.com"
        ) as client:
            assert isinstance(client, Connector)
        mock_close.assert_called_once()


def test_wikipedia_client_user_agent() -> None:
    """Verifies that the User-Agent header is built and set correctly."""
    app_name = "TestApp"
    contact_email = "test@example.com"
    version = "2.1"
    client = WikipediaClient(
        app_name=app_name, contact_email=contact_email, version=version
    )

    expected_ua = (
        f"{app_name}/{version} (contact: {contact_email}) httpx/{httpx.__version__}"
    )
    assert client.client.headers["User-Agent"] == expected_ua
    client.close()


def test_rate_limiting_invalid_retry_after() -> None:
    """Verifies that 429 rate limiting with an invalid Retry-After header

    defaults to 60 seconds.
    """
    client = WikipediaClient(
        app_name="TestApp", contact_email="test@example.com", max_retries=1
    )

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "not-an-integer"}

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    with pytest.raises(WikipediaRateLimitError) as exc_info:
        client.get_random_article_summary()

    # Should default to 60
    assert exc_info.value.retry_after == 60
    assert "Please retry after 60 seconds." in str(exc_info.value)
    client.close()


def test_http_status_error_non_429() -> None:
    """Verifies that any other HTTP status error (e.g. 500) raises WikipediaAPIError."""
    client = WikipediaClient(
        app_name="TestApp", contact_email="test@example.com", max_retries=1
    )

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    request = httpx.Request("GET", "https://en.wikipedia.org/foo")
    exc = httpx.HTTPStatusError("500 Error", request=request, response=mock_response)
    mock_response.raise_for_status.side_effect = exc

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    with pytest.raises(WikipediaAPIError) as exc_info:
        client.get_random_article_summary()

    assert "HTTP Error 500: Internal Server Error" in str(exc_info.value)
    client.close()


@patch("time.sleep", return_value=None)
def test_transient_network_error_retry_success(mock_sleep: MagicMock) -> None:
    """Verifies that transient network errors are retried and eventually succeed."""
    client = WikipediaClient(
        app_name="TestApp", contact_email="test@example.com", max_retries=3
    )

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "title": "Success",
        "extract": "Abstract",
        "content_urls": {"desktop": {"page": "https://url"}},
    }

    request = httpx.Request("GET", "https://en.wikipedia.org")
    client.client.get = MagicMock(  # type: ignore[method-assign]
        side_effect=[
            httpx.NetworkError("Network down", request=request),
            httpx.TimeoutException("Timeout", request=request),
            mock_response,
        ]
    )

    summary = client.get_random_article_summary()
    assert summary["title"] == "Success"
    assert client.client.get.call_count == 3
    assert mock_sleep.call_count == 2
    client.close()


@patch("time.sleep", return_value=None)
def test_transient_network_error_exhausted(mock_sleep: MagicMock) -> None:
    """Verifies that if retries are exhausted, WikipediaNetworkError is raised."""
    client = WikipediaClient(
        app_name="TestApp", contact_email="test@example.com", max_retries=3
    )

    request = httpx.Request("GET", "https://en.wikipedia.org")
    client.client.get = MagicMock(  # type: ignore[method-assign]
        side_effect=httpx.NetworkError("Fatal connection error", request=request)
    )

    with pytest.raises(WikipediaNetworkError) as exc_info:
        client.get_random_article_summary()

    assert "Connection failed after 3 attempts" in str(exc_info.value)
    assert client.client.get.call_count == 3
    assert mock_sleep.call_count == 2
    client.close()


def test_get_article_full_text_missing_pages() -> None:
    """Verifies that empty pages structure raises WikipediaAPIError."""
    client = WikipediaClient(app_name="TestApp", contact_email="test@example.com")

    mock_data: dict[str, Any] = {"query": {}}

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    with pytest.raises(WikipediaAPIError) as exc_info:
        client.get_article_full_text("NonExistentArticle")

    assert "No pages found in Wikipedia response structure." in str(exc_info.value)
    client.close()


def test_get_article_full_text_article_missing() -> None:
    """Verifies that an article that does not exist raises WikipediaAPIError."""
    client = WikipediaClient(app_name="TestApp", contact_email="test@example.com")

    mock_data = {
        "query": {
            "pages": {
                "-1": {
                    "ns": 0,
                    "title": "NonExistent",
                    "missing": "",
                }
            }
        }
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    with pytest.raises(WikipediaAPIError) as exc_info:
        client.get_article_full_text("NonExistent")

    assert "Article titled 'NonExistent' does not exist on Wikipedia." in str(
        exc_info.value
    )
    client.close()


def test_get_article_full_text_extract_not_string() -> None:
    """Verifies default return message if extract is not a string."""
    client = WikipediaClient(app_name="TestApp", contact_email="test@example.com")

    mock_data = {
        "query": {
            "pages": {
                "12345": {
                    "pageid": 12345,
                    "title": "Python",
                    "extract": None,
                }
            }
        }
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    full_text = client.get_article_full_text("Python")
    assert full_text == "No content text available."
    client.close()


def test_http_status_error_429_raised_by_fn() -> None:
    """Verifies that if the request_fn itself raises HTTPStatusError with 429,

    it is reraised.
    """
    client = WikipediaClient(
        app_name="TestApp", contact_email="test@example.com", max_retries=1
    )

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429

    request = httpx.Request("GET", "https://en.wikipedia.org/foo")
    exc = httpx.HTTPStatusError("429 Error", request=request, response=mock_response)

    # We call _execute_with_backoff with a function that raises this exception directly
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        client._execute_with_backoff(MagicMock(side_effect=exc))

    assert exc_info.value.response.status_code == 429
    client.close()


def test_unreachable_state_retries_zero() -> None:
    """Verifies that if max_retries is 0, the client raises WikipediaAPIError

    for unreachable state.
    """
    client = WikipediaClient(
        app_name="TestApp", contact_email="test@example.com", max_retries=0
    )
    with pytest.raises(WikipediaAPIError) as exc_info:
        client.get_random_article_summary()
    assert "Unreachable state in client backoff routine." in str(exc_info.value)
    client.close()
