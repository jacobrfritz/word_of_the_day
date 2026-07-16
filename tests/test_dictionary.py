from unittest.mock import MagicMock, patch

import httpx

from word_of_the_day.dictionary import (
    DictionaryClient,
    clean_mw_markup,
    extract_free_dict_definition,
)


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
        client.base_url = "https://www.dictionaryapi.com/api/v3/references/collegiate/json/"
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
    """Verifies that when the MW key is missing the client falls back to
    Free Dictionary, and returns False if that also fails (404).
    """
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 404

    with DictionaryClient() as client:
        client.api_key = None
        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result, origin = client.get_word_definition("hello")

    assert is_valid is False
    assert result == "Not a valid English word."
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
    suggestions and Free Dictionary also cannot find the word.
    """
    with DictionaryClient() as client:
        client.api_key = "dummy_key"
        with patch.object(
            client,
            "_fetch_from_merriam_webster",
            return_value=(False, "Not a valid English word.", None),
        ):
            with patch.object(
                client,
                "_fetch_from_free_dictionary",
                return_value=(False, "Not a valid English word.", None),
            ):
                is_valid, result, origin = client.get_word_definition("impetu")

        assert is_valid is False
        assert result == "Not a valid English word."
        assert origin is None


def test_dictionary_client_api_error() -> None:
    """Verifies _fetch_from_merriam_webster returns False on other status codes."""
    with DictionaryClient() as client:
        client.api_key = "dummy_key"
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500

        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result, origin = client._fetch_from_merriam_webster("hello")

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
    """Verifies get_word_definition handles an empty MW response by falling
    back to Free Dictionary, returning False if that also fails.
    """
    with DictionaryClient() as client:
        client.api_key = "dummy_key"
        with patch.object(
            client,
            "_fetch_from_merriam_webster",
            return_value=(False, "Not a valid English word.", None),
        ):
            with patch.object(
                client,
                "_fetch_from_free_dictionary",
                return_value=(False, "Not a valid English word.", None),
            ):
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


# ---------------------------------------------------------------------------
# Free Dictionary fallback tests
# ---------------------------------------------------------------------------


def test_extract_free_dict_definition() -> None:
    """Unit-tests the Free Dictionary API response parser."""
    data = [
        {
            "word": "soliloquy",
            "meanings": [
                {
                    "partOfSpeech": "noun",
                    "definitions": [
                        {"definition": "the act of speaking one's thoughts aloud"}
                    ],
                }
            ],
        }
    ]
    part_of_speech, definition = extract_free_dict_definition(data)
    assert part_of_speech == "noun"
    assert definition == "the act of speaking one's thoughts aloud"

    # Malformed / empty inputs
    assert extract_free_dict_definition([]) == ("unknown", None)
    assert extract_free_dict_definition(["not a dict"]) == ("unknown", None)
    assert extract_free_dict_definition([{"word": "test"}]) == ("unknown", None)
    assert extract_free_dict_definition([{"meanings": []}]) == ("unknown", None)


def test_free_dict_fallback_when_mw_key_missing() -> None:
    """When the MW key is absent the client falls back to Free Dictionary
    and returns True when that source succeeds.
    """
    free_dict_data = [
        {
            "word": "soliloquy",
            "meanings": [
                {
                    "partOfSpeech": "noun",
                    "definitions": [
                        {"definition": "the act of speaking one's thoughts aloud"}
                    ],
                }
            ],
        }
    ]
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = free_dict_data

    with DictionaryClient() as client:
        client.api_key = None
        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result, origin = client.get_word_definition("soliloquy")

    assert is_valid is True
    assert result == "(noun) the act of speaking one's thoughts aloud"
    assert origin is None


def test_free_dict_fallback_when_mw_word_not_found() -> None:
    """When MW returns 'not a valid word', Free Dictionary is tried as fallback."""
    with DictionaryClient() as client:
        client.api_key = "dummy_key"
        with patch.object(
            client,
            "_fetch_from_merriam_webster",
            return_value=(False, "Not a valid English word.", None),
        ):
            with patch.object(
                client,
                "_fetch_from_free_dictionary",
                return_value=(
                    True,
                    "(adjective) given to sudden and unaccountable changes of mood",
                    None,
                ),
            ):
                is_valid, result, origin = client.get_word_definition("capricious")

    assert is_valid is True
    assert "(adjective)" in result
    assert origin is None


def test_free_dict_fallback_when_mw_network_error() -> None:
    """When MW raises a network error, Free Dictionary is tried as fallback."""
    with DictionaryClient() as client:
        client.api_key = "dummy_key"
        with patch.object(
            client,
            "_fetch_from_merriam_webster",
            return_value=(False, "Network validation failed: Connection timed out", None),
        ):
            with patch.object(
                client,
                "_fetch_from_free_dictionary",
                return_value=(True, "(noun) the act of speaking one's thoughts aloud", None),
            ):
                is_valid, result, origin = client.get_word_definition("soliloquy")

    assert is_valid is True
    assert "(noun)" in result
    assert origin is None


def test_both_sources_fail() -> None:
    """When both MW and Free Dictionary fail, the final result is (False, ...)."""
    with DictionaryClient() as client:
        client.api_key = "dummy_key"
        with patch.object(
            client,
            "_fetch_from_merriam_webster",
            return_value=(False, "Not a valid English word.", None),
        ):
            with patch.object(
                client,
                "_fetch_from_free_dictionary",
                return_value=(False, "Not a valid English word.", None),
            ):
                is_valid, result, origin = client.get_word_definition("xyzzy")

    assert is_valid is False
    assert result == "Not a valid English word."
    assert origin is None


def test_free_dict_not_called_on_mw_success() -> None:
    """Free Dictionary is NOT invoked when Merriam-Webster succeeds (efficiency)."""
    with DictionaryClient() as client:
        client.api_key = "dummy_key"
        with patch.object(
            client,
            "_fetch_from_merriam_webster",
            return_value=(True, "(noun) a greeting", "Middle English"),
        ) as mock_mw:
            with patch.object(
                client, "_fetch_from_free_dictionary"
            ) as mock_fd:
                is_valid, result, origin = client.get_word_definition("hello")

    assert is_valid is True
    mock_mw.assert_called_once_with("hello")
    mock_fd.assert_not_called()


def test_free_dict_api_error() -> None:
    """Verifies _fetch_from_free_dictionary handles non-200/404 status codes."""
    with DictionaryClient() as client:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500

        with patch.object(client.session, "get", return_value=mock_response):
            is_valid, result, origin = client._fetch_from_free_dictionary("hello")

    assert is_valid is False
    assert "Free Dictionary API error" in result
    assert origin is None
