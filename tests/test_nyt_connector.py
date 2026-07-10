from unittest.mock import MagicMock, patch

import httpx
import pytest

from word_of_the_day.connectors import (
    Connector,
    NewYorkTimesAPIError,
    NewYorkTimesClient,
    NewYorkTimesNetworkError,
    NewYorkTimesRateLimitError,
)


def test_nyt_client_implements_protocol() -> None:
    """Verifies that NewYorkTimesClient satisfies the Connector protocol."""
    assert issubclass(NewYorkTimesClient, Connector)

    client = NewYorkTimesClient(api_key="dummy_key")
    assert isinstance(client, Connector)
    client.close()


def test_nyt_client_initialization() -> None:
    """Verifies initialization logic and parameter validation."""
    # Successful initialization
    client = NewYorkTimesClient(api_key="test_key", start_year=2000, end_year=2020)
    assert client.api_key == "test_key"
    assert client.start_year == 2000
    assert client.end_year == 2020
    client.close()

    # Empty API key should raise error
    with pytest.raises(NewYorkTimesAPIError) as exc_info:
        NewYorkTimesClient(api_key="")
    assert "API key must be a non-empty string" in str(exc_info.value)

    # Invalid years (start > end) should raise error
    with pytest.raises(NewYorkTimesAPIError) as exc_info:
        NewYorkTimesClient(api_key="test_key", start_year=2020, end_year=2010)
    assert "start_year cannot be greater than end_year" in str(exc_info.value)


@patch("random.randint")
@patch("random.shuffle")
def test_fetch_text_corpus_success(
    mock_shuffle: MagicMock, mock_randint: MagicMock
) -> None:
    """Verifies that fetch_text_corpus handles a successful JSON response
    with lead_paragraph.
    """
    client = NewYorkTimesClient(api_key="dummy_key", start_year=2020, end_year=2020)

    # Mock random inputs to control page & month
    mock_randint.side_effect = [2020, 5, 1]  # year, month, page

    mock_data = {
        "status": "OK",
        "response": {
            "docs": [
                {
                    "lead_paragraph": "This is a great NYT lead paragraph.",
                    "abstract": "This is the abstract.",
                    "snippet": "This is the snippet.",
                }
            ]
        },
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data

    client.client.get = MagicMock(return_value=mock_response)

    corpus = client.fetch_text_corpus()

    assert corpus == "This is a great NYT lead paragraph."
    client.client.get.assert_called_once()
    # Check that query parameters were sent correctly
    called_args, called_kwargs = client.client.get.call_args
    params = called_kwargs.get("params", {})
    assert params.get("begin_date") == "20200501"
    assert params.get("end_date") == "20200531"
    assert params.get("page") == 1
    assert params.get("api-key") == "dummy_key"
    client.close()


@patch("random.randint")
def test_fetch_text_corpus_abstract_fallback(mock_randint: MagicMock) -> None:
    """Verifies fallback to abstract when lead_paragraph is missing/empty."""
    client = NewYorkTimesClient(api_key="dummy_key", start_year=2020, end_year=2020)
    mock_randint.side_effect = [2020, 6, 0]

    mock_data = {
        "response": {
            "docs": [
                {
                    "lead_paragraph": "",
                    "abstract": "Fall back to this abstract text.",
                    "snippet": "Snippet text.",
                }
            ]
        }
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data

    client.client.get = MagicMock(return_value=mock_response)

    corpus = client.fetch_text_corpus()
    assert corpus == "Fall back to this abstract text."
    client.close()


@patch("random.randint")
def test_fetch_text_corpus_snippet_fallback(mock_randint: MagicMock) -> None:
    """Verifies fallback to snippet when lead_paragraph and abstract
    are missing/empty.
    """
    client = NewYorkTimesClient(api_key="dummy_key", start_year=2020, end_year=2020)
    mock_randint.side_effect = [2020, 7, 0]

    mock_data = {
        "response": {
            "docs": [
                {
                    "lead_paragraph": None,
                    "abstract": None,
                    "snippet": "Fall back to this snippet text.",
                }
            ]
        }
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data

    client.client.get = MagicMock(return_value=mock_response)

    corpus = client.fetch_text_corpus()
    assert corpus == "Fall back to this snippet text."
    client.close()


@patch("random.randint")
def test_fetch_text_corpus_empty_docs_retry(mock_randint: MagicMock) -> None:
    """Verifies that the client retries with a new query if the initial
    response contains no docs.
    """
    client = NewYorkTimesClient(api_key="dummy_key", start_year=2020, end_year=2020)

    # Mock two rounds of year, month, page
    mock_randint.side_effect = [2020, 1, 0, 2020, 2, 1]

    # First response: no documents
    mock_response_empty = MagicMock(spec=httpx.Response)
    mock_response_empty.status_code = 200
    mock_response_empty.json.return_value = {"response": {"docs": []}}

    # Second response: has documents
    mock_response_success = MagicMock(spec=httpx.Response)
    mock_response_success.status_code = 200
    mock_response_success.json.return_value = {
        "response": {
            "docs": [
                {
                    "lead_paragraph": "Success text on second attempt.",
                }
            ]
        }
    }

    client.client.get = MagicMock(
        side_effect=[mock_response_empty, mock_response_success]
    )

    corpus = client.fetch_text_corpus()

    assert corpus == "Success text on second attempt."
    assert client.client.get.call_count == 2
    client.close()


def test_fetch_text_corpus_rate_limiting() -> None:
    """Verifies that HTTP 429 raises a NewYorkTimesRateLimitError."""
    client = NewYorkTimesClient(api_key="dummy_key", max_retries=1)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "30"}

    client.client.get = MagicMock(return_value=mock_response)

    with pytest.raises(NewYorkTimesRateLimitError) as exc_info:
        client.fetch_text_corpus()

    assert exc_info.value.retry_after == 30
    assert "Please retry after 30 seconds." in str(exc_info.value)
    client.close()


def test_fetch_text_corpus_network_error() -> None:
    """Verifies that network/timeout exceptions raise NewYorkTimesNetworkError."""
    client = NewYorkTimesClient(api_key="dummy_key", max_retries=1)

    client.client.get = MagicMock(side_effect=httpx.NetworkError("Network down"))

    with pytest.raises(NewYorkTimesNetworkError) as exc_info:
        client.fetch_text_corpus()

    assert "Connection failed after 1 attempts" in str(exc_info.value)
    client.close()


def test_fetch_text_corpus_http_error() -> None:
    """Verifies that other HTTP status errors raise NewYorkTimesAPIError."""
    client = NewYorkTimesClient(api_key="dummy_key", max_retries=1)

    # Mock response for a 500 error
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_response.request = MagicMock()

    # Throw HTTPStatusError
    exc = httpx.HTTPStatusError(
        "500 Server Error",
        request=mock_response.request,
        response=mock_response,
    )
    client.client.get = MagicMock(side_effect=exc)

    with pytest.raises(NewYorkTimesAPIError) as exc_info:
        client.fetch_text_corpus()

    assert "HTTP Error 500: Internal Server Error" in str(exc_info.value)
    client.close()


def test_context_manager() -> None:
    """Verifies context manager usage and correct cleanup of the client
    connection pool.
    """
    with patch.object(httpx.Client, "close") as mock_close:
        with NewYorkTimesClient(api_key="dummy_key") as client:
            assert isinstance(client, Connector)
        mock_close.assert_called_once()
