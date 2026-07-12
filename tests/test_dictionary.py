from unittest.mock import MagicMock, patch

import httpx

from word_of_the_day.dictionary import DictionaryClient, clean_mw_markup


def test_clean_mw_markup() -> None:
    """Verifies that clean_mw_markup correctly cleans MW markup tags."""
    assert clean_mw_markup("{it}cannabis{/it} hemp") == "cannabis hemp"
    assert clean_mw_markup("{bc}marked by force") == ": marked by force"
    assert clean_mw_markup("greeting {a_link|word} text") == "greeting word text"
    assert clean_mw_markup("see {sx|taciturn||} here") == "see taciturn here"
    assert clean_mw_markup("refer to {d_link|word|definition}") == "refer to word"
    assert clean_mw_markup(None) is None
    assert clean_mw_markup("") == ""


def test_dictionary_client_context_manager() -> None:
    """Verifies DictionaryClient context manager protocol works correctly."""
    with patch.object(httpx.Client, "close") as mock_close:
        with DictionaryClient() as client:
            assert isinstance(client, DictionaryClient)
            assert isinstance(client.session, httpx.Client)

    mock_close.assert_called_once()


def test_dictionary_client_success() -> None:
    """Verifies get_word_definition returns True, formatted definition,
    and origin on 200 with valid Merriam-Webster Collegiate response.
    """
    with DictionaryClient() as client:
        client.api_key = "dummy_key"
        mock_data = [
            {
                "fl": "noun",
                "et": [["text", "Middle English, from Latin {it}cannabis{/it}"]],
                "def": [
                    {
                        "sseq": [
                            [
                                [
                                    "sense",
                                    {
                                        "dt": [
                                            [
                                                "text",
                                                "{bc}an utterance of 'hello' as a {a_link|greeting}",
                                            ]
                                        ]
                                    },
                                ]
                            ]
                        ]
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
        assert result == "(noun) : an utterance of 'hello' as a greeting"
        assert origin == "Middle English, from Latin cannabis"
        mock_get.assert_called_once_with(
            "https://www.dictionaryapi.com/api/v3/references/collegiate/json/hello?key=dummy_key"
        )


def test_dictionary_client_missing_key() -> None:
    """Verifies get_word_definition returns False when key is missing."""
    with DictionaryClient() as client:
        client.api_key = None
        is_valid, result, origin = client.get_word_definition("hello")
        assert is_valid is False
        assert "Configuration error" in result
        assert origin is None


def test_dictionary_client_not_found() -> None:
    """Verifies get_word_definition returns False on 404."""
    with DictionaryClient() as client:
        client.api_key = "dummy_key"
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 404

        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result, origin = client.get_word_definition("invalidword")

        assert is_valid is False
        assert result == "Not a valid English word."
        assert origin is None


def test_dictionary_client_spelling_suggestions() -> None:
    """Verifies get_word_definition returns False when MW returns spelling
    suggestions instead of word entry data.
    """
    with DictionaryClient() as client:
        client.api_key = "dummy_key"
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        # MW returns list of strings for suggestions
        mock_response.json.return_value = ["impetus", "impulse"]

        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result, origin = client.get_word_definition("impetu")

        assert is_valid is False
        assert result == "Not a valid English word."
        assert origin is None


def test_dictionary_client_api_error() -> None:
    """Verifies get_word_definition returns False on other status codes."""
    with DictionaryClient() as client:
        client.api_key = "dummy_key"
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
        client.api_key = "dummy_key"
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
        client.api_key = "dummy_key"
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = []

        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result, origin = client.get_word_definition("hello")

        assert is_valid is False
        assert result == "Not a valid English word."
        assert origin is None


def test_dictionary_client_no_definitions() -> None:
    """Verifies get_word_definition handles response with no definitions list."""
    with DictionaryClient() as client:
        client.api_key = "dummy_key"
        mock_data = [
            {
                "fl": "noun",
                "et": [],
                "def": [],
            }
        ]
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_data

        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result, origin = client.get_word_definition("hello")

        assert is_valid is True
        assert result == "(noun) No definition text found."
        assert origin is None


def test_dictionary_client_caching() -> None:
    """Verifies that DictionaryClient utilizes storage caching when available."""
    mock_storage = MagicMock()

    # 1. Test Cache Hit
    # Setup cache: (is_valid, definition, origin)
    mock_storage.get_cached_definition.return_value = (True, "(noun) cached definition", "cached origin")

    with DictionaryClient(storage=mock_storage) as client:
        is_valid, result, origin = client.get_word_definition("cachedword")

    assert is_valid is True
    assert result == "(noun) cached definition"
    assert origin == "cached origin"
    mock_storage.get_cached_definition.assert_called_once_with("cachedword")

    # 2. Test Cache Miss
    # Setup cache: None (miss)
    mock_storage.get_cached_definition.reset_mock()
    mock_storage.get_cached_definition.return_value = None

    # Mock definition API call response
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "fl": "noun",
            "et": [["text", "Middle English"]],
            "def": [
                {
                    "sseq": [[["sense", {"dt": [["text", "a greeting"]]}]]]
                }
            ]
        }
    ]

    with DictionaryClient(storage=mock_storage) as client:
        client.api_key = "dummy_key"
        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result, origin = client.get_word_definition("missword")

    assert is_valid is True
    assert result == "(noun) a greeting"
    assert origin == "Middle English"
    mock_storage.get_cached_definition.assert_called_once_with("missword")
    mock_storage.cache_definition.assert_called_once_with("missword", True, "(noun) a greeting", "Middle English")

