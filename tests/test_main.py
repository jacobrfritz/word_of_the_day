# tests/test_main.py
import logging
import os
from unittest.mock import MagicMock, patch

import pytest

from word_of_the_day import main


def test_run(capsys: pytest.CaptureFixture[str]) -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    try:
        main.run(source="wikipedia")
    finally:
        # Clean up any handlers added by setup_logging in main.run()
        for handler in list(root_logger.handlers):
            if handler not in original_handlers:
                handler.close()
                root_logger.removeHandler(handler)
        root_logger.handlers = original_handlers
        root_logger.setLevel(original_level)

    captured = capsys.readouterr()
    # Check that stdout has captured console formatting logs
    assert "Starting the Word of the Day analysis pipeline." in captured.out
    assert "WORD OF THE DAY CANDIDATES" in captured.out
    assert "Pipeline finished. Successfully validated and defined" in captured.out


@patch("word_of_the_day.connectors.WikipediaClient")
@patch("word_of_the_day.connectors.GutenbergClient")
@patch("word_of_the_day.connectors.NewYorkTimesClient")
@patch("word_of_the_day.connectors.QuotableClient")
@patch("word_of_the_day.connectors.PoetryDBClient")
@patch("word_of_the_day.connectors.SubstackClient")
@patch("word_of_the_day.generator.WordSourceGenerator")
@patch("word_of_the_day.pipeline.WordOfTheDayPipeline")
def test_run_default(
    mock_pipeline_class: MagicMock,
    mock_generator_class: MagicMock,
    mock_substack_class: MagicMock,
    mock_poetry_class: MagicMock,
    mock_quotable_class: MagicMock,
    mock_nyt_class: MagicMock,
    mock_gutenberg_class: MagicMock,
    mock_wiki_class: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_wiki = MagicMock()
    mock_wiki_class.return_value = mock_wiki
    mock_gutenberg = MagicMock()
    mock_gutenberg_class.return_value = mock_gutenberg
    mock_nyt = MagicMock()
    mock_nyt_class.return_value = mock_nyt
    mock_quotable = MagicMock()
    mock_quotable_class.return_value = mock_quotable
    mock_poetry = MagicMock()
    mock_poetry_class.return_value = mock_poetry
    mock_substack = MagicMock()
    mock_substack_class.return_value = mock_substack

    mock_generator = MagicMock()
    mock_generator.__enter__.return_value = mock_generator
    mock_generator.fetch_sources.return_value = "some text content"
    mock_generator_class.return_value = mock_generator

    mock_pipeline = MagicMock()
    mock_pipeline.__enter__.return_value = mock_pipeline
    mock_candidate = MagicMock()
    mock_candidate.word = "serendipity"
    mock_candidate.zipf_score = 3.5
    mock_candidate.definition = "(noun) standard def"
    mock_pipeline.find_candidates.return_value = [mock_candidate]
    mock_pipeline_class.return_value = mock_pipeline

    with patch.dict(os.environ, {"NYT_API_KEY": "test_key"}):
        main.run()

    mock_wiki_class.assert_called_once()
    mock_gutenberg_class.assert_called_once()
    mock_nyt_class.assert_called_once_with(api_key="test_key")
    mock_quotable_class.assert_called_once()
    mock_poetry_class.assert_called_once()
    mock_substack_class.assert_called_once_with(
        category="philosophy",
        limit_publications=3,
        limit_posts_per_pub=3,
    )
    mock_generator_class.assert_called_once_with(
        [
            mock_wiki,
            mock_gutenberg,
            mock_nyt,
            mock_quotable,
            mock_poetry,
            mock_substack,
        ]
    )
    captured = capsys.readouterr()
    assert "SERENDIPITY" in captured.out


@patch("word_of_the_day.connectors.WikipediaClient")
@patch("word_of_the_day.generator.WordSourceGenerator")
@patch("word_of_the_day.pipeline.WordOfTheDayPipeline")
def test_main_wikipedia(
    mock_pipeline_class: MagicMock,
    mock_generator_class: MagicMock,
    mock_wiki_class: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_wiki = MagicMock()
    mock_wiki_class.return_value = mock_wiki

    mock_generator = MagicMock()
    mock_generator.__enter__.return_value = mock_generator
    mock_generator.fetch_sources.return_value = "some text content"
    mock_generator_class.return_value = mock_generator

    mock_pipeline = MagicMock()
    mock_pipeline.__enter__.return_value = mock_pipeline
    mock_candidate = MagicMock()
    mock_candidate.word = "serendipity"
    mock_candidate.zipf_score = 3.5
    mock_candidate.definition = "(noun) standard def"
    mock_pipeline.find_candidates.return_value = [mock_candidate]
    mock_pipeline_class.return_value = mock_pipeline

    main.run(source="wikipedia")

    mock_wiki_class.assert_called_once_with(
        app_name="WordOfTheDayApp",
        contact_email="fritz@example.com",
        version="1.0.0",
    )
    captured = capsys.readouterr()
    assert "SERENDIPITY" in captured.out


@patch("word_of_the_day.connectors.GutenbergClient")
@patch("word_of_the_day.generator.WordSourceGenerator")
@patch("word_of_the_day.pipeline.WordOfTheDayPipeline")
def test_main_gutenberg(
    mock_pipeline_class: MagicMock,
    mock_generator_class: MagicMock,
    mock_gutenberg_class: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_gutenberg = MagicMock()
    mock_gutenberg_class.return_value = mock_gutenberg

    mock_generator = MagicMock()
    mock_generator.__enter__.return_value = mock_generator
    mock_generator.fetch_sources.return_value = "some text content"
    mock_generator_class.return_value = mock_generator

    mock_pipeline = MagicMock()
    mock_pipeline.__enter__.return_value = mock_pipeline
    mock_candidate = MagicMock()
    mock_candidate.word = "serendipity"
    mock_candidate.zipf_score = 3.5
    mock_candidate.definition = "(noun) standard def"
    mock_pipeline.find_candidates.return_value = [mock_candidate]
    mock_pipeline_class.return_value = mock_pipeline

    main.run(source="gutenberg", book_id="1234")

    mock_gutenberg_class.assert_called_once_with(book_id="1234")
    captured = capsys.readouterr()
    assert "SERENDIPITY" in captured.out


@patch("word_of_the_day.connectors.NewYorkTimesClient")
@patch("word_of_the_day.generator.WordSourceGenerator")
@patch("word_of_the_day.pipeline.WordOfTheDayPipeline")
def test_main_nyt(
    mock_pipeline_class: MagicMock,
    mock_generator_class: MagicMock,
    mock_nyt_class: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_nyt = MagicMock()
    mock_nyt_class.return_value = mock_nyt

    mock_generator = MagicMock()
    mock_generator.__enter__.return_value = mock_generator
    mock_generator.fetch_sources.return_value = "some text content"
    mock_generator_class.return_value = mock_generator

    mock_pipeline = MagicMock()
    mock_pipeline.__enter__.return_value = mock_pipeline
    mock_candidate = MagicMock()
    mock_candidate.word = "serendipity"
    mock_candidate.zipf_score = 3.5
    mock_candidate.definition = "(noun) standard def"
    mock_pipeline.find_candidates.return_value = [mock_candidate]
    mock_pipeline_class.return_value = mock_pipeline

    with patch.dict(os.environ, {"NYT_API_KEY": "test_key"}):
        main.run(source="nyt")

    mock_nyt_class.assert_called_once_with(api_key="test_key")
    captured = capsys.readouterr()
    assert "SERENDIPITY" in captured.out


@patch("word_of_the_day.connectors.NewYorkTimesClient")
@patch("dotenv.load_dotenv")
def test_main_nyt_missing_api_key(
    mock_load_dotenv: MagicMock,
    mock_nyt_class: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch.dict(os.environ, {}, clear=True):
        main.run(source="nyt")

    mock_nyt_class.assert_not_called()


@patch("word_of_the_day.connectors.QuotableClient")
@patch("word_of_the_day.generator.WordSourceGenerator")
@patch("word_of_the_day.pipeline.WordOfTheDayPipeline")
def test_main_quotable(
    mock_pipeline_class: MagicMock,
    mock_generator_class: MagicMock,
    mock_quotable_class: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_quotable = MagicMock()
    mock_quotable_class.return_value = mock_quotable

    mock_generator = MagicMock()
    mock_generator.__enter__.return_value = mock_generator
    mock_generator.fetch_sources.return_value = "some text content"
    mock_generator_class.return_value = mock_generator

    mock_pipeline = MagicMock()
    mock_pipeline.__enter__.return_value = mock_pipeline
    mock_candidate = MagicMock()
    mock_candidate.word = "serendipity"
    mock_candidate.zipf_score = 3.5
    mock_candidate.definition = "(noun) standard def"
    mock_pipeline.find_candidates.return_value = [mock_candidate]
    mock_pipeline_class.return_value = mock_pipeline

    main.run(source="quotable", tags="tag1, tag2")

    mock_quotable_class.assert_called_once_with(tags=["tag1", "tag2"])
    captured = capsys.readouterr()
    assert "SERENDIPITY" in captured.out


@patch("word_of_the_day.connectors.PoetryDBClient")
@patch("word_of_the_day.generator.WordSourceGenerator")
@patch("word_of_the_day.pipeline.WordOfTheDayPipeline")
def test_main_poetry_db(
    mock_pipeline_class: MagicMock,
    mock_generator_class: MagicMock,
    mock_poetry_class: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_poetry = MagicMock()
    mock_poetry_class.return_value = mock_poetry

    mock_generator = MagicMock()
    mock_generator.__enter__.return_value = mock_generator
    mock_generator.fetch_sources.return_value = "some text content"
    mock_generator_class.return_value = mock_generator

    mock_pipeline = MagicMock()
    mock_pipeline.__enter__.return_value = mock_pipeline
    mock_candidate = MagicMock()
    mock_candidate.word = "serendipity"
    mock_candidate.zipf_score = 3.5
    mock_candidate.definition = "(noun) standard def"
    mock_pipeline.find_candidates.return_value = [mock_candidate]
    mock_pipeline_class.return_value = mock_pipeline

    main.run(source="poetry_db", author="Edgar Allan Poe, John Keats")

    mock_poetry_class.assert_called_once_with(author=["Edgar Allan Poe", "John Keats"])
    captured = capsys.readouterr()
    assert "SERENDIPITY" in captured.out


@patch("word_of_the_day.connectors.WikipediaClient")
@patch("word_of_the_day.connectors.PoetryDBClient")
@patch("word_of_the_day.generator.WordSourceGenerator")
@patch("word_of_the_day.pipeline.WordOfTheDayPipeline")
def test_main_multiple_sources(
    mock_pipeline_class: MagicMock,
    mock_generator_class: MagicMock,
    mock_poetry_class: MagicMock,
    mock_wiki_class: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_wiki = MagicMock()
    mock_wiki_class.return_value = mock_wiki
    mock_poetry = MagicMock()
    mock_poetry_class.return_value = mock_poetry

    mock_generator = MagicMock()
    mock_generator.__enter__.return_value = mock_generator
    mock_generator.fetch_sources.return_value = "some text content"
    mock_generator_class.return_value = mock_generator

    mock_pipeline = MagicMock()
    mock_pipeline.__enter__.return_value = mock_pipeline
    mock_candidate = MagicMock()
    mock_candidate.word = "serendipity"
    mock_candidate.zipf_score = 3.5
    mock_candidate.definition = "(noun) standard def"
    mock_pipeline.find_candidates.return_value = [mock_candidate]
    mock_pipeline_class.return_value = mock_pipeline

    main.run(source=["wikipedia", "poetry_db"], author="Edgar Allan Poe")

    mock_wiki_class.assert_called_once_with(
        app_name="WordOfTheDayApp",
        contact_email="fritz@example.com",
        version="1.0.0",
    )
    mock_poetry_class.assert_called_once_with(author="Edgar Allan Poe")
    mock_generator_class.assert_called_once_with([mock_wiki, mock_poetry])
    captured = capsys.readouterr()
    assert "SERENDIPITY" in captured.out


@patch("word_of_the_day.connectors.WikipediaClient")
@patch("word_of_the_day.connectors.GutenbergClient")
@patch("word_of_the_day.connectors.NewYorkTimesClient")
@patch("word_of_the_day.connectors.QuotableClient")
@patch("word_of_the_day.connectors.PoetryDBClient")
@patch("word_of_the_day.connectors.SubstackClient")
@patch("word_of_the_day.generator.WordSourceGenerator")
@patch("word_of_the_day.pipeline.WordOfTheDayPipeline")
def test_main_all_sources(
    mock_pipeline_class: MagicMock,
    mock_generator_class: MagicMock,
    mock_substack_class: MagicMock,
    mock_poetry_class: MagicMock,
    mock_quotable_class: MagicMock,
    mock_nyt_class: MagicMock,
    mock_gutenberg_class: MagicMock,
    mock_wiki_class: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_wiki = MagicMock()
    mock_wiki_class.return_value = mock_wiki
    mock_gutenberg = MagicMock()
    mock_gutenberg_class.return_value = mock_gutenberg
    mock_nyt = MagicMock()
    mock_nyt_class.return_value = mock_nyt
    mock_quotable = MagicMock()
    mock_quotable_class.return_value = mock_quotable
    mock_poetry = MagicMock()
    mock_poetry_class.return_value = mock_poetry
    mock_substack = MagicMock()
    mock_substack_class.return_value = mock_substack

    mock_generator = MagicMock()
    mock_generator.__enter__.return_value = mock_generator
    mock_generator.fetch_sources.return_value = "some text content"
    mock_generator_class.return_value = mock_generator

    mock_pipeline = MagicMock()
    mock_pipeline.__enter__.return_value = mock_pipeline
    mock_candidate = MagicMock()
    mock_candidate.word = "serendipity"
    mock_candidate.zipf_score = 3.5
    mock_candidate.definition = "(noun) standard def"
    mock_pipeline.find_candidates.return_value = [mock_candidate]
    mock_pipeline_class.return_value = mock_pipeline

    with patch.dict(os.environ, {"NYT_API_KEY": "test_key"}):
        main.run(source="all")

    mock_wiki_class.assert_called_once()
    mock_gutenberg_class.assert_called_once()
    mock_nyt_class.assert_called_once_with(api_key="test_key")
    mock_quotable_class.assert_called_once()
    mock_poetry_class.assert_called_once()
    mock_substack_class.assert_called_once_with(
        category="philosophy",
        limit_publications=3,
        limit_posts_per_pub=3,
    )
    mock_generator_class.assert_called_once_with(
        [
            mock_wiki,
            mock_gutenberg,
            mock_nyt,
            mock_quotable,
            mock_poetry,
            mock_substack,
        ]
    )
    captured = capsys.readouterr()
    assert "SERENDIPITY" in captured.out
