from unittest.mock import MagicMock, patch

import httpx
import pytest

from word_of_the_day.connectors import (
    Connector,
    QuotableAPIError,
    QuotableClient,
    QuotableNetworkError,
    QuotableRateLimitError,
)


def test_quotable_client_implements_protocol() -> None:
    """Verifies that QuotableClient satisfies the Connector protocol."""
    assert issubclass(QuotableClient, Connector)

    client = QuotableClient()
    assert isinstance(client, Connector)
    client.close()


def test_quotable_client_initialization() -> None:
    """Verifies initialization logic and parameter parsing."""
    # 1. Default initialization
    client = QuotableClient()
    assert client.tags is None
    assert client.quotes_per_fetch == 20
    assert str(client.client.base_url) == "https://api.quotable.io"
    client.close()

    # 2. Custom initialization
    client_custom = QuotableClient(
        tags=["literature", "wisdom"],
        quotes_per_fetch=5,
        base_url="https://mirror.quotable.io",
        timeout=5.0,
    )
    assert client_custom.tags == ["literature", "wisdom"]
    assert client_custom.quotes_per_fetch == 5
    assert str(client_custom.client.base_url) == "https://mirror.quotable.io"
    client_custom.close()


def test_fetch_text_corpus_success() -> None:
    """Verifies that fetch_text_corpus handles a successful JSON response."""
    client = QuotableClient(tags=["literature", "wisdom"], quotes_per_fetch=2)

    mock_data = [
        {
            "_id": "1",
            "content": "To be or not to be.",
            "author": "William Shakespeare",
            "tags": ["literature"],
        },
        {
            "_id": "2",
            "content": "The only true wisdom is in knowing you know nothing.",
            "author": "Socrates",
            "tags": ["wisdom"],
        },
    ]

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    corpus = client.fetch_text_corpus()

    expected_corpus = (
        "To be or not to be. -- William Shakespeare\n\n"
        "The only true wisdom is in knowing you know nothing. -- Socrates"
    )
    assert corpus == expected_corpus

    client.client.get.assert_called_once()
    called_args, called_kwargs = client.client.get.call_args
    assert called_args[0] == "/quotes/random"
    params = called_kwargs.get("params", {})
    assert params.get("tags") == "literature|wisdom"
    assert params.get("limit") == 2
    client.close()


def test_fetch_text_corpus_single_object_response() -> None:
    """Verifies that fetch_text_corpus handles a single dictionary response format."""
    client = QuotableClient(tags="wisdom")

    mock_data = {
        "_id": "3",
        "content": "Think twice, speak once.",
        "author": "John Doe",
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    corpus = client.fetch_text_corpus()
    assert corpus == "Think twice, speak once. -- John Doe"
    client.close()


def test_rate_limiting() -> None:
    """Verifies that 429 rate limiting throws a QuotableRateLimitError."""
    client = QuotableClient(max_retries=1)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "15"}

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    with pytest.raises(QuotableRateLimitError) as exc_info:
        client.fetch_text_corpus()

    assert exc_info.value.retry_after == 15
    assert "Please retry after 15 seconds." in str(exc_info.value)
    client.close()


def test_rate_limiting_invalid_retry_after() -> None:
    """Verifies that 429 rate limiting with an invalid Retry-After header

    defaults to 60.
    """
    client = QuotableClient(max_retries=1)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "invalid-int"}

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    with pytest.raises(QuotableRateLimitError) as exc_info:
        client.fetch_text_corpus()

    assert exc_info.value.retry_after == 60
    assert "Please retry after 60 seconds." in str(exc_info.value)
    client.close()


def test_http_status_error_non_429() -> None:
    """Verifies that any other HTTP status error (e.g. 500) raises QuotableAPIError."""
    client = QuotableClient(max_retries=1)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    request = httpx.Request("GET", "https://api.quotable.io/quotes/random")
    exc = httpx.HTTPStatusError("500 Error", request=request, response=mock_response)
    mock_response.raise_for_status.side_effect = exc

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    with pytest.raises(QuotableAPIError) as exc_info:
        client.fetch_text_corpus()

    assert "HTTP Error 500: Internal Server Error" in str(exc_info.value)
    client.close()


@patch("time.sleep", return_value=None)
def test_transient_network_error_retry_success(mock_sleep: MagicMock) -> None:
    """Verifies that transient network errors are retried and eventually succeed."""
    client = QuotableClient(max_retries=3)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = [{"content": "Success quote", "author": "Famous"}]

    request = httpx.Request("GET", "https://api.quotable.io/quotes/random")
    client.client.get = MagicMock(  # type: ignore[method-assign]
        side_effect=[
            httpx.NetworkError("Network down", request=request),
            httpx.TimeoutException("Timeout", request=request),
            mock_response,
        ]
    )

    corpus = client.fetch_text_corpus()
    assert corpus == "Success quote -- Famous"
    assert client.client.get.call_count == 3
    assert mock_sleep.call_count == 2
    client.close()


@patch("time.sleep", return_value=None)
def test_transient_network_error_exhausted(mock_sleep: MagicMock) -> None:
    """Verifies that if retries are exhausted, QuotableNetworkError is raised."""
    client = QuotableClient(max_retries=3)

    request = httpx.Request("GET", "https://api.quotable.io/quotes/random")
    client.client.get = MagicMock(  # type: ignore[method-assign]
        side_effect=httpx.NetworkError("Fatal connection error", request=request)
    )

    with pytest.raises(QuotableNetworkError) as exc_info:
        client.fetch_text_corpus()

    assert "Connection failed after 3 attempts" in str(exc_info.value)
    assert client.client.get.call_count == 3
    assert mock_sleep.call_count == 2
    client.close()


def test_fetch_text_corpus_empty_response() -> None:
    """Verifies that empty list response raises QuotableAPIError."""
    client = QuotableClient()

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = []

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    with pytest.raises(QuotableAPIError) as exc_info:
        client.fetch_text_corpus()

    assert "No quotes returned from Quotable API." in str(exc_info.value)
    client.close()


def test_fetch_text_corpus_no_valid_text() -> None:
    """Verifies that responses with missing content raise QuotableAPIError."""
    client = QuotableClient()

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = [{"content": "", "author": "Nobody"}]

    client.client.get = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    with pytest.raises(QuotableAPIError) as exc_info:
        client.fetch_text_corpus()

    assert "Quotes found, but none contained valid text." in str(exc_info.value)
    client.close()


def test_context_manager() -> None:
    """Verifies that the context manager correctly closes the client."""
    with patch.object(httpx.Client, "close") as mock_close:
        with QuotableClient() as client:
            assert isinstance(client, Connector)
        mock_close.assert_called_once()
