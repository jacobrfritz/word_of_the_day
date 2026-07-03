from unittest.mock import MagicMock, patch

import requests
from word_of_the_day.dictionary import DictionaryClient


def test_dictionary_client_context_manager() -> None:
    """Verifies DictionaryClient context manager protocol works correctly."""
    # Use patch.object to mock session.close to satisfy mypy
    with patch.object(requests.Session, "close") as mock_close:
        with DictionaryClient() as client:
            assert isinstance(client, DictionaryClient)
            assert isinstance(client.session, requests.Session)
        # Exiting context manager triggers close

    mock_close.assert_called_once()


def test_dictionary_client_success() -> None:
    """Verifies get_word_definition returns True and formatted definition on 200."""
    with DictionaryClient() as client:
        mock_data = [
            {
                "word": "hello",
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
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_data

        with patch.object(
            client.session, "get", return_value=mock_response
        ) as mock_get:
            is_valid, result = client.get_word_definition("hello")

        assert is_valid is True
        assert result == "(noun) An utterance of 'hello' as a greeting."
        mock_get.assert_called_once_with(
            "https://api.dictionaryapi.dev/api/v2/entries/en/hello", timeout=5.0
        )


def test_dictionary_client_not_found() -> None:
    """Verifies get_word_definition returns False on 404."""
    with DictionaryClient() as client:
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 404

        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result = client.get_word_definition("invalidword")

        assert is_valid is False
        assert result == "Not a valid English word."


def test_dictionary_client_api_error() -> None:
    """Verifies get_word_definition returns False on other status codes."""
    with DictionaryClient() as client:
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 500

        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result = client.get_word_definition("hello")

        assert is_valid is False
        assert "API error status code: 500" in result


def test_dictionary_client_network_error() -> None:
    """Verifies get_word_definition handles requests exceptions gracefully."""
    with DictionaryClient() as client:
        with patch.object(
            client.session,
            "get",
            side_effect=requests.RequestException("Connection timed out"),
        ):
            is_valid, result = client.get_word_definition("hello")

        assert is_valid is False
        assert "Network validation failed:" in result


def test_dictionary_client_empty_response() -> None:
    """Verifies get_word_definition handles unexpected response formats."""
    with DictionaryClient() as client:
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        # Empty list response
        mock_response.json.return_value = []

        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result = client.get_word_definition("hello")

        assert is_valid is True
        assert result == "Word is valid, but no definition layout was found."


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
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_data

        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result = client.get_word_definition("hello")

        assert is_valid is True
        assert result == "Word is valid, but no definition layout was found."
