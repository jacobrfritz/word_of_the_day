import urllib.parse
from unittest.mock import MagicMock, patch

import httpx
import pytest

from word_of_the_day.connectors import (
    Connector,
    PoetryDBAPIError,
    PoetryDBClient,
    PoetryDBNetworkError,
    PoetryDBRateLimitError,
)
from word_of_the_day.connectors.poetry_db import DEFAULT_CLASSIC_POETS


def test_poetry_db_client_implements_protocol() -> None:
    """Verifies that PoetryDBClient satisfies the Connector protocol."""
    assert issubclass(PoetryDBClient, Connector)

    client = PoetryDBClient()
    assert isinstance(client, Connector)
    client.close()


def test_poetry_db_client_initialization() -> None:
    """Verifies initialization logic with default, random, and custom authors."""
    # 1. Default (None)
    client_default = PoetryDBClient()
    assert client_default.author is None

    # 2. String "random"
    client_random = PoetryDBClient(author="random")
    assert client_random.author == "random"

    # 3. Custom string/list
    client_custom = PoetryDBClient(author="Edgar Allan Poe")
    assert client_custom.author == "Edgar Allan Poe"

    client_list = PoetryDBClient(author=["Edgar Allan Poe", "Lord Byron"])
    assert client_list.author == ["Edgar Allan Poe", "Lord Byron"]

    # 4. Invalid author type
    with pytest.raises(PoetryDBAPIError) as exc_info:
        PoetryDBClient(author=123)  # type: ignore
    assert "author must be None, a string, or a list of strings" in str(exc_info.value)


@patch("time.sleep", return_value=None)
def test_fetch_text_corpus_global_success(mock_sleep: MagicMock) -> None:
    """Verifies successful global random poem retrieval (author='any')."""
    client = PoetryDBClient(author="any")

    mock_data = [
        {
            "title": "A Dream Within a Dream",
            "author": "Edgar Allan Poe",
            "lines": ["Take this kiss upon the brow!", "And, in parting from you now,"],
            "linecount": "2",
        }
    ]

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data

    client.client.get = MagicMock(return_value=mock_response)

    corpus = client.fetch_text_corpus()

    assert corpus == "Take this kiss upon the brow!\nAnd, in parting from you now,"
    client.client.get.assert_called_once_with("/random/1")
    client.close()


@patch("time.sleep", return_value=None)
def test_fetch_text_corpus_author_success(mock_sleep: MagicMock) -> None:
    """Verifies successful two-step retrieval for a specific author."""
    client = PoetryDBClient(author="Edgar Allan Poe")

    mock_titles_data = [{"title": "A Dream Within a Dream"}]
    mock_poem_data = [
        {
            "title": "A Dream Within a Dream",
            "author": "Edgar Allan Poe",
            "lines": ["Take this kiss upon the brow!", "And, in parting from you now,"],
            "linecount": "2",
        }
    ]

    mock_titles_response = MagicMock(spec=httpx.Response)
    mock_titles_response.status_code = 200
    mock_titles_response.json.return_value = mock_titles_data

    mock_poem_response = MagicMock(spec=httpx.Response)
    mock_poem_response.status_code = 200
    mock_poem_response.json.return_value = mock_poem_data

    client.client.get = MagicMock(
        side_effect=[mock_titles_response, mock_poem_response]
    )

    corpus = client.fetch_text_corpus()

    assert corpus == "Take this kiss upon the brow!\nAnd, in parting from you now,"
    assert client.client.get.call_count == 2

    # Verify parameters were quoted correctly
    quoted_author = urllib.parse.quote("Edgar Allan Poe")
    quoted_title = urllib.parse.quote("A Dream Within a Dream")
    client.client.get.assert_any_call(f"/author/{quoted_author}/title")
    client.client.get.assert_any_call(f"/author,title/{quoted_author};{quoted_title}")

    client.close()


@patch("time.sleep", return_value=None)
def test_fetch_text_corpus_curated_random_author(mock_sleep: MagicMock) -> None:
    """Verifies that author=None resolves to a curated classic poet."""
    client = PoetryDBClient(author=None)

    mock_titles_data = [{"title": "Random Classic Poem"}]
    mock_poem_data = [
        {
            "title": "Random Classic Poem",
            "author": "Some Poet",
            "lines": ["Classic verse 1", "Classic verse 2"],
            "linecount": "2",
        }
    ]

    mock_titles_response = MagicMock(spec=httpx.Response)
    mock_titles_response.status_code = 200
    mock_titles_response.json.return_value = mock_titles_data

    mock_poem_response = MagicMock(spec=httpx.Response)
    mock_poem_response.status_code = 200
    mock_poem_response.json.return_value = mock_poem_data

    client.client.get = MagicMock(
        side_effect=[mock_titles_response, mock_poem_response]
    )

    def side_effect(seq):
        if seq == DEFAULT_CLASSIC_POETS:
            return "John Keats"
        return seq[0]

    patch_path = "word_of_the_day.connectors.poetry_db.random.choice"
    with patch(patch_path, side_effect=side_effect) as mock_choice:
        corpus = client.fetch_text_corpus()
        mock_choice.assert_any_call(DEFAULT_CLASSIC_POETS)

    assert corpus == "Classic verse 1\nClassic verse 2"
    client.close()


@patch("time.sleep", return_value=None)
def test_fetch_text_corpus_author_list(mock_sleep: MagicMock) -> None:
    """Verifies that author list resolves to a random choice from the list."""
    author_list = ["Edgar Allan Poe", "Lord Byron"]
    client = PoetryDBClient(author=author_list)

    mock_titles_data = [{"title": "List Poem"}]
    mock_poem_data = [
        {
            "title": "List Poem",
            "author": "Some Poet",
            "lines": ["List line 1", "List line 2"],
            "linecount": "2",
        }
    ]

    mock_titles_response = MagicMock(spec=httpx.Response)
    mock_titles_response.status_code = 200
    mock_titles_response.json.return_value = mock_titles_data

    mock_poem_response = MagicMock(spec=httpx.Response)
    mock_poem_response.status_code = 200
    mock_poem_response.json.return_value = mock_poem_data

    client.client.get = MagicMock(
        side_effect=[mock_titles_response, mock_poem_response]
    )

    def side_effect(seq):
        if seq == author_list:
            return "Lord Byron"
        return seq[0]

    patch_path = "word_of_the_day.connectors.poetry_db.random.choice"
    with patch(patch_path, side_effect=side_effect) as mock_choice:
        corpus = client.fetch_text_corpus()
        mock_choice.assert_any_call(author_list)

    assert corpus == "List line 1\nList line 2"
    client.close()


def test_fetch_text_corpus_empty_author_list() -> None:
    """Verifies that an empty author list raises an exception."""
    client = PoetryDBClient(author=[])
    with pytest.raises(PoetryDBAPIError) as exc_info:
        client.fetch_text_corpus()
    assert "Author list cannot be empty" in str(exc_info.value)
    client.close()


def test_rate_limiting() -> None:
    """Verifies that 429 rate limiting raises PoetryDBRateLimitError."""
    client = PoetryDBClient(author="any", max_retries=1)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "15"}

    client.client.get = MagicMock(return_value=mock_response)

    with pytest.raises(PoetryDBRateLimitError) as exc_info:
        client.fetch_text_corpus()

    assert exc_info.value.retry_after == 15
    assert "Please retry after 15 seconds." in str(exc_info.value)
    client.close()


def test_rate_limiting_invalid_retry_after() -> None:
    """Verifies that 429 rate limiting with invalid Retry-After defaults to 60s."""
    client = PoetryDBClient(author="any", max_retries=1)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "invalid-int"}

    client.client.get = MagicMock(return_value=mock_response)

    with pytest.raises(PoetryDBRateLimitError) as exc_info:
        client.fetch_text_corpus()

    assert exc_info.value.retry_after == 60
    client.close()


@patch("time.sleep", return_value=None)
def test_transient_network_error_retry_success(mock_sleep: MagicMock) -> None:
    """Verifies transient network failures are retried and can succeed."""
    client = PoetryDBClient(author="any", max_retries=3)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = [{"lines": ["Line 1"]}]

    request = httpx.Request("GET", "https://poetrydb.org")
    client.client.get = MagicMock(
        side_effect=[
            httpx.NetworkError("Network issue", request=request),
            httpx.TimeoutException("Timeout issue", request=request),
            mock_response,
        ]
    )

    corpus = client.fetch_text_corpus()
    assert corpus == "Line 1"
    assert client.client.get.call_count == 3
    assert mock_sleep.call_count == 2
    client.close()


@patch("time.sleep", return_value=None)
def test_transient_network_error_exhausted(mock_sleep: MagicMock) -> None:
    """Verifies that exhausted retries raise PoetryDBNetworkError."""
    client = PoetryDBClient(author="any", max_retries=3)

    request = httpx.Request("GET", "https://poetrydb.org")
    client.client.get = MagicMock(
        side_effect=httpx.NetworkError("Fatal network error", request=request)
    )

    with pytest.raises(PoetryDBNetworkError) as exc_info:
        client.fetch_text_corpus()

    assert "Connection failed after 3 attempts" in str(exc_info.value)
    assert client.client.get.call_count == 3
    assert mock_sleep.call_count == 2
    client.close()


def test_api_status_error_response() -> None:
    """Verifies that API error responses (like 404 dicts) raise PoetryDBAPIError."""
    client = PoetryDBClient(author="any")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": 404, "reason": "Not found"}

    client.client.get = MagicMock(return_value=mock_response)

    with pytest.raises(PoetryDBAPIError) as exc_info:
        client.fetch_text_corpus()

    assert "API Error 404: Not found" in str(exc_info.value)
    client.close()


def test_api_unexpected_non_list() -> None:
    """Verifies unexpected JSON structures raise PoetryDBAPIError."""
    client = PoetryDBClient(author="any")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = "unexpected string response"

    client.client.get = MagicMock(return_value=mock_response)

    with pytest.raises(PoetryDBAPIError) as exc_info:
        client.fetch_text_corpus()

    assert "Unexpected empty response from PoetryDB." in str(exc_info.value)
    client.close()


def test_api_missing_lines() -> None:
    """Verifies missing 'lines' list raises PoetryDBAPIError."""
    client = PoetryDBClient(author="any")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = [{"title": "Title Without Lines"}]

    client.client.get = MagicMock(return_value=mock_response)

    with pytest.raises(PoetryDBAPIError) as exc_info:
        client.fetch_text_corpus()

    assert "Poem format is invalid: missing 'lines'" in str(exc_info.value)
    client.close()


def test_context_manager() -> None:
    """Verifies the context manager exits and closes the client connection pool."""
    with patch.object(httpx.Client, "close") as mock_close:
        with PoetryDBClient() as client:
            assert isinstance(client, Connector)
        mock_close.assert_called_once()


@patch.dict("os.environ", {}, clear=True)
def test_poetry_db_client_user_agent() -> None:
    """Verifies that compliant User-Agent headers are set correctly."""
    client = PoetryDBClient()
    expected_ua_prefix = "WordOfTheDay/1.0 (contact: fritz@example.com)"
    assert client.client.headers["User-Agent"].startswith(expected_ua_prefix)
    client.close()


def test_unreachable_state_retries_zero() -> None:
    """Verifies that max_retries <= 0 raises PoetryDBAPIError immediately."""
    client = PoetryDBClient(author="any", max_retries=0)
    with pytest.raises(PoetryDBAPIError) as exc_info:
        client.fetch_text_corpus()
    assert "Unreachable state" in str(exc_info.value)
    client.close()
