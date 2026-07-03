from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from word_of_the_day import DictionaryClient, WordCandidate, WordOfTheDayPipeline


def test_pipeline_stop_words_loading_iterable() -> None:
    """Verifies pipeline correctly initializes with stop words from iterable."""
    pipeline = WordOfTheDayPipeline(stop_words={"the", "and"})
    assert "the" in pipeline.stop_words
    assert "and" in pipeline.stop_words
    assert "apple" not in pipeline.stop_words

    pipeline_list = WordOfTheDayPipeline(stop_words=["a", "of"])
    assert "a" in pipeline_list.stop_words
    assert "of" in pipeline_list.stop_words


def test_pipeline_stop_words_loading_file(tmp_path: Path) -> None:
    """Verifies that the pipeline correctly loads stop words from a file path."""
    words_file = tmp_path / "custom_stop_words.txt"
    words_file.write_text("Hello\nWORLD\n  test\n", encoding="utf-8")

    pipeline = WordOfTheDayPipeline(stop_words=words_file)
    assert pipeline.stop_words == {"hello", "world", "test"}


def test_pipeline_stop_words_loading_default() -> None:
    """Verifies that default stop words load correctly or log warning when missing."""
    # Since stop_words.txt is at the root directory of the workspace, it should load.
    pipeline = WordOfTheDayPipeline(stop_words=None)
    assert len(pipeline.stop_words) > 0
    assert "the" in pipeline.stop_words


def test_pipeline_stop_words_loading_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Verifies pipeline behavior and logging when stop words file fails to read."""
    stop_words_file = tmp_path / "stop_words.txt"
    stop_words_file.write_text("hello", encoding="utf-8")
    with patch.object(
        Path, "read_text", side_effect=ValueError("Unexpected read error")
    ):
        pipeline = WordOfTheDayPipeline(stop_words=stop_words_file)
        assert pipeline.stop_words == set()
        assert any("Failed to load stop words" in r.message for r in caplog.records)


def test_pipeline_clean_text() -> None:
    """Verifies text cleaning logic (lowercasing, punctuation, stop words)."""
    pipeline = WordOfTheDayPipeline(stop_words={"the", "a", "is"})

    # Mixed case, punctuation, stop words
    raw_text = "The quick brown fox jumps! Over the lazy dog's back... Is it? YES."
    cleaned = pipeline.clean_text(raw_text)

    # Expected cleaned: "quick", "brown", "fox", "jumps", "over",
    # "lazy", "dog's", "back", "it", "yes"
    assert "quick" in cleaned
    assert "fox" in cleaned
    assert "dog's" in cleaned
    assert "the" not in cleaned
    assert "is" not in cleaned
    assert "jumps" in cleaned
    assert "yes" in cleaned
    # Non-alpha filtering check: punctuation-only like ! or ... should be removed
    assert "" not in cleaned
    assert "!" not in cleaned


def test_pipeline_score_and_filter() -> None:
    """Verifies that frequency scoring, filtering, and sorting work correctly."""
    pipeline = WordOfTheDayPipeline(stop_words=set())

    # We want to test Zipf frequency scores. Let's score some words:
    # "the" is extremely common (Zipf > 6)
    # "and" is extremely common (Zipf > 6)
    # "serendipity" is rare (Zipf ~ 2.5)
    # "valid" is intermediate (Zipf ~ 4.2)
    # "syzygy" is rare but has a score > 0 (Zipf ~ 1.4)
    words = {"the", "and", "serendipity", "valid", "syzygy"}

    # Default goldilocks range: 2.3 < score <= 4.0
    scored = pipeline.score_and_filter(words)

    # "serendipity" should be in the list.
    # "the" and "and" should be filtered out (too common, > 4.0).
    # "syzygy" should be filtered out (too rare, <= 2.3).
    # "valid" should be filtered out (too common, > 4.0).
    assert len(scored) == 1
    assert scored[0][0] == "serendipity"
    assert 2.3 < scored[0][1] <= 4.0

    # Custom range: 0.0 < score <= 10.0 (keeps all)
    scored_all = pipeline.score_and_filter(words, min_score=0.0, max_score=10.0)
    assert len(scored_all) == 5
    # Should be sorted ascending by zipf score (rarest first)
    assert scored_all[0][0] == "syzygy"  # rarest
    assert scored_all[-1][0] in {"the", "and"}  # most common


def test_pipeline_validate_candidates() -> None:
    """Verifies that the validation checks definitions and respect the limit."""
    mock_dict_client = MagicMock(spec=DictionaryClient)

    # Mock definition lookups
    # "rareword1" is valid
    # "rareword2" is invalid (not a valid English word)
    # "rareword3" is valid
    def get_def_mock(word: str) -> tuple[bool, str]:
        if word == "rareword1":
            return True, "(noun) definition 1"
        if word == "rareword2":
            return False, "Not a valid English word."
        if word == "rareword3":
            return True, "(verb) definition 3"
        return False, "Not found"

    mock_dict_client.get_word_definition.side_effect = get_def_mock

    pipeline = WordOfTheDayPipeline(
        stop_words=set(), dictionary_client=mock_dict_client
    )

    candidates = [
        ("rareword1", 2.5),
        ("rareword2", 2.6),
        ("rareword3", 2.7),
    ]

    # Validate candidates (limit=1)
    results_limit_1 = pipeline.validate_candidates(candidates, limit=1)
    assert len(results_limit_1) == 1
    assert results_limit_1[0] == WordCandidate(
        word="rareword1", zipf_score=2.5, definition="(noun) definition 1"
    )

    # Validate candidates (limit=3)
    # rareword2 is invalid, so only rareword1 and rareword3 should be returned.
    results_limit_3 = pipeline.validate_candidates(candidates, limit=3)
    assert len(results_limit_3) == 2
    assert results_limit_3[0].word == "rareword1"
    assert results_limit_3[1].word == "rareword3"


def test_pipeline_find_candidates_full_run() -> None:
    """Verifies the complete find_candidates flow runs successfully."""
    mock_dict_client = MagicMock(spec=DictionaryClient)
    mock_dict_client.get_word_definition.return_value = (True, "(noun) test definition")

    pipeline = WordOfTheDayPipeline(
        stop_words={"the", "and"}, dictionary_client=mock_dict_client
    )

    # Input text containing serendipity
    text = "the serendipity and other words"
    candidates = pipeline.find_candidates(text)

    # serendipity should match (Zipf is in goldilocks range and not a stop word)
    assert len(candidates) >= 1
    assert any(c.word == "serendipity" for c in candidates)


def test_pipeline_context_manager() -> None:
    """Verifies using pipeline as a context manager closes the dictionary client."""
    mock_dict_client = MagicMock(spec=DictionaryClient)
    with WordOfTheDayPipeline(
        stop_words=set(), dictionary_client=mock_dict_client
    ) as pipeline:
        assert pipeline.dictionary_client == mock_dict_client

    # When using external client, context manager should NOT close it by default
    mock_dict_client.close.assert_not_called()

    # When using internal client, it should close it
    with patch("word_of_the_day.pipeline.DictionaryClient") as mock_dict_class:
        mock_internal_client = MagicMock()
        mock_dict_class.return_value = mock_internal_client

        with WordOfTheDayPipeline(stop_words=set()):
            pass

        mock_internal_client.close.assert_called_once()


def test_pipeline_validate_candidates_skips_invalid_to_fulfill_limit() -> None:
    """Verifies that validate_candidates continues scanning until it fulfills

    the limit of valid words, rather than slicing early.
    """
    mock_dict_client = MagicMock(spec=DictionaryClient)

    def get_def_mock(word: str) -> tuple[bool, str]:
        if word == "rareword1":
            return True, "definition 1"
        if word == "rareword2":
            return False, "Not a valid English word."
        if word == "rareword3":
            return True, "definition 3"
        return False, "Not found"

    mock_dict_client.get_word_definition.side_effect = get_def_mock

    pipeline = WordOfTheDayPipeline(
        stop_words=set(), dictionary_client=mock_dict_client
    )

    candidates = [
        ("rareword1", 2.5),
        ("rareword2", 2.6),
        ("rareword3", 2.7),
    ]

    # Validate candidates (limit=2)
    # Under old logic, early slicing would check only rareword1 and rareword2,
    # returning only 1 candidate. Under new logic, it checks rareword3 as well
    # and returns both valid candidates.
    results = pipeline.validate_candidates(candidates, limit=2)
    assert len(results) == 2
    assert results[0].word == "rareword1"
    assert results[1].word == "rareword3"
