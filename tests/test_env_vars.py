import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import bootstrap_word_of_the_day
from word_of_the_day.connectors.new_york_times import NewYorkTimesClient
from word_of_the_day.connectors.poetry_db import PoetryDBClient
from word_of_the_day.connectors.quotable import QuotableClient
from word_of_the_day.connectors.substack import SubstackClient
from word_of_the_day.connectors.wikipedia import WikipediaClient
from word_of_the_day.dictionary import DictionaryClient
from word_of_the_day.main import run


def test_nyt_base_url_env_var() -> None:
    """Verifies NewYorkTimesClient respects NYT_BASE_URL env var."""
    with patch.dict(os.environ, {"NYT_BASE_URL": "https://test.nyt.com"}):
        client = NewYorkTimesClient(api_key="dummy_key")
        assert str(client.client.base_url).rstrip("/") == "https://test.nyt.com"
        client.close()


def test_poetry_db_env_vars() -> None:
    """Verifies PoetryDBClient respects POETRY_DB env vars."""
    env_overrides = {
        "POETRY_DB_BASE_URL": "https://test.poetrydb.org",
        "POETRY_DB_APP_NAME": "TestPoetryApp",
        "POETRY_DB_VERSION": "2.0",
        "POETRY_DB_CONTACT_EMAIL": "test@poetry.com",
    }
    with patch.dict(os.environ, env_overrides):
        client = PoetryDBClient()
        assert str(client.client.base_url).rstrip("/") == "https://test.poetrydb.org"
        ua_header = client.client.headers.get("user-agent")
        assert "TestPoetryApp/2.0" in ua_header
        assert "test@poetry.com" in ua_header
        client.close()


def test_quotable_base_url_env_var() -> None:
    """Verifies QuotableClient respects QUOTABLE_BASE_URL env var."""
    with patch.dict(os.environ, {"QUOTABLE_BASE_URL": "https://test.quotable.io"}):
        client = QuotableClient()
        assert str(client.client.base_url).rstrip("/") == "https://test.quotable.io"
        client.close()


def test_substack_base_url_env_var() -> None:
    """Verifies SubstackClient respects SUBSTACK_BASE_URL env var."""
    with patch.dict(os.environ, {"SUBSTACK_BASE_URL": "https://test.substack.com"}):
        client = SubstackClient()
        assert str(client.client.base_url).rstrip("/") == "https://test.substack.com"
        client.close()


def test_wikipedia_base_url_env_var() -> None:
    """Verifies WikipediaClient respects WIKIPEDIA_BASE_URL env var."""
    with patch.dict(os.environ, {"WIKIPEDIA_BASE_URL": "https://test.wikipedia.org"}):
        client = WikipediaClient(app_name="App", contact_email="email")
        assert str(client.client.base_url).rstrip("/") == "https://test.wikipedia.org"
        client.close()


def test_dictionary_base_url_env_var() -> None:
    """Verifies DictionaryClient respects DICTIONARY_BASE_URL env var."""
    with patch.dict(
        os.environ, {"DICTIONARY_BASE_URL": "https://test.dictionaryapi.dev/"}
    ):
        client = DictionaryClient()
        assert client.base_url == "https://test.dictionaryapi.dev/"
        client.close()


@patch("word_of_the_day.main.setup_logging")
@patch("word_of_the_day.generator.WordSourceGenerator")
def test_main_run_logging_env_vars(
    mock_generator: MagicMock, mock_setup_logging: MagicMock
) -> None:
    """Verifies main.run configures logging and variables from environment."""
    env_overrides = {
        "LOG_FILE": "test_logs/app.log",
        "LOG_LEVEL_CONSOLE": "WARNING",
        "LOG_LEVEL_FILE": "CRITICAL",
        "LOG_MAX_BYTES": "2048",
        "LOG_BACKUP_COUNT": "3",
    }
    with patch.dict(os.environ, env_overrides):
        # Run with dummy sources to prevent full pipeline run
        run(source=[])
        mock_setup_logging.assert_called_once_with(
            log_file=Path("test_logs/app.log"),
            console_level=logging.WARNING,
            file_level=logging.CRITICAL,
            rotation_type="size",
            max_bytes=2048,
            backup_count=3,
        )


@patch("bootstrap_word_of_the_day.requests.get")
def test_bootstrap_feed_url_env_var(mock_get: MagicMock) -> None:
    """Verifies bootstrap_word_of_the_day respects PODCAST_FEED_URL env var."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"<rss></rss>"
    mock_get.return_value = mock_response

    with patch.dict(os.environ, {"PODCAST_FEED_URL": "https://test.rss.feed/merriam"}):
        bootstrap_word_of_the_day.fetch_new_words()
        mock_get.assert_called_once()
        called_url = mock_get.call_args[0][0]
        assert called_url == "https://test.rss.feed/merriam"
