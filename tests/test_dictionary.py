from unittest.mock import MagicMock, patch

import httpx

from word_of_the_day.dictionary import DictionaryClient


def test_dictionary_client_context_manager() -> None:
    """Verifies DictionaryClient context manager protocol works correctly."""
    with patch.object(httpx.Client, "close") as mock_close:
        with DictionaryClient() as client:
            assert isinstance(client, DictionaryClient)
            assert isinstance(client.session, httpx.Client)

    mock_close.assert_called_once()


def test_dictionary_client_success() -> None:
    """Verifies get_word_definition returns True, formatted definition,
    and origin on 200.
    """
    with DictionaryClient() as client:
        mock_data = [
            {
                "word": "hello",
                "origin": "early 19th century...",
                "meanings": [
                    {
                        "partOfSpeech": "noun",
                        "definitions": [
                            {"definition": "An utterance of 'hello' as a greeting."}
                        ],
                    }
                ],
            }
        ]
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_data

        with patch.object(
            client.session, "get", return_value=mock_response
        ) as mock_get:
            is_valid, result, origin = client.get_word_definition("hello")

        assert is_valid is True
        assert result == "(noun) An utterance of 'hello' as a greeting."
        assert origin == "early 19th century..."
        mock_get.assert_called_once_with(
            "https://api.dictionaryapi.dev/api/v2/entries/en/hello"
        )


def test_dictionary_client_not_found() -> None:
    """Verifies get_word_definition returns False on 404."""
    with DictionaryClient() as client:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 404

        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result, origin = client.get_word_definition("invalidword")

        assert is_valid is False
        assert result == "Not a valid English word."
        assert origin is None


def test_dictionary_client_api_error() -> None:
    """Verifies get_word_definition returns False on other status codes."""
    with DictionaryClient() as client:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500

        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result, origin = client.get_word_definition("hello")

        assert is_valid is False
        assert "API error status code: 500" in result
        assert origin is None


def test_dictionary_client_network_error() -> None:
    """Verifies get_word_definition handles HTTPError exceptions gracefully."""
    with DictionaryClient() as client:
        with patch.object(
            client.session,
            "get",
            side_effect=httpx.HTTPError("Connection timed out"),
        ):
            is_valid, result, origin = client.get_word_definition("hello")

        assert is_valid is False
        assert "Network validation failed:" in result
        assert origin is None


def test_dictionary_client_empty_response() -> None:
    """Verifies get_word_definition handles unexpected response formats."""
    with DictionaryClient() as client:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = []

        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result, origin = client.get_word_definition("hello")

        assert is_valid is True
        assert result == "Word is valid, but no definition layout was found."
        assert origin is None


def test_dictionary_client_no_definitions() -> None:
    """Verifies get_word_definition handles response with meanings but no
    definitions.
    """
    with DictionaryClient() as client:
        mock_data = [
            {
                "word": "hello",
                "meanings": [
                    {
                        "partOfSpeech": "noun",
                        "definitions": [],
                    }
                ],
            }
        ]
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_data

        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result, origin = client.get_word_definition("hello")

        assert is_valid is True
        assert result == "Word is valid, but no definition layout was found."
        assert origin is None
