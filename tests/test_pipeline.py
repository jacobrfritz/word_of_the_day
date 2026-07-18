from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from word_of_the_day import (
    DictionaryClient,
    TFIDFScorer,
    WordCandidate,
    WordOfTheDayPipeline,
    ZipfScorer,
)


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
    pipeline = WordOfTheDayPipeline(
        stop_words={"the", "a", "is"}, use_lemmatization=False
    )

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
    """Verifies that POS tagging, length filtering, and sorting work correctly."""
    pipeline = WordOfTheDayPipeline(stop_words=set(), scorer=ZipfScorer())

    # "the" -> DET (determiner)
    # "and" -> CONJ (conjunction)
    # "serendipity" -> NOUN
    # "valid" -> ADJ
    # "jumped" -> VERB
    # "go" -> VERB
    words = {"the", "and", "serendipity", "valid", "jumped", "go"}

    # Mock settings to defaults (True for NOUN, ADJ, VERB; None for lengths)
    with patch("word_of_the_day.pipeline.settings") as mock_settings:
        mock_settings.pos_filter_nouns = True
        mock_settings.pos_filter_adjectives = True
        mock_settings.pos_filter_verbs = True
        mock_settings.min_word_length = None
        mock_settings.max_word_length = None

        scored = pipeline.score_and_filter(words)
        filtered_words = {item[0] for item in scored}

        # "the" (DET) and "and" (CONJ) should be filtered out
        # "serendipity" (NOUN), "valid" (ADJ), "jumped" (VERB), "go" (VERB) should be kept
        assert "the" not in filtered_words
        assert "and" not in filtered_words
        assert "serendipity" in filtered_words
        assert "valid" in filtered_words
        assert "jumped" in filtered_words
        assert "go" in filtered_words

        # Test length filters
        mock_settings.min_word_length = 4
        mock_settings.max_word_length = 10
        scored_len = pipeline.score_and_filter(words)
        filtered_len_words = {item[0] for item in scored_len}
        # "go" is length 2 (filtered out by min)
        # "serendipity" is length 11 (filtered out by max)
        # "valid" (length 5) and "jumped" (length 6) should be kept
        assert "go" not in filtered_len_words
        assert "serendipity" not in filtered_len_words
        assert "valid" in filtered_len_words
        assert "jumped" in filtered_len_words

        # Test toggles: disable nouns
        mock_settings.min_word_length = None
        mock_settings.max_word_length = None
        mock_settings.pos_filter_nouns = False
        scored_no_nouns = pipeline.score_and_filter(words)
        filtered_no_nouns = {item[0] for item in scored_no_nouns}
        assert "serendipity" not in filtered_no_nouns
        assert "valid" in filtered_no_nouns
        assert "jumped" in filtered_no_nouns
        assert "go" in filtered_no_nouns


def test_pipeline_validate_candidates() -> None:
    """Verifies that the validation checks definitions and respect the limit."""
    mock_dict_client = MagicMock(spec=DictionaryClient)

    # Mock definition lookups
    # "rareword1" is valid
    # "rareword2" is invalid (not a valid English word)
    # "rareword3" is valid
    def get_def_mock(word: str) -> tuple[bool, str, str | None]:
        if word == "rareword1":
            return True, "(noun) definition 1", "origin 1"
        if word == "rareword2":
            return False, "Not a valid English word.", None
        if word == "rareword3":
            return True, "(verb) definition 3", None
        return False, "Not found", None

    mock_dict_client.get_word_definition.side_effect = get_def_mock

    pipeline = WordOfTheDayPipeline(
        stop_words=set(), dictionary_client=mock_dict_client, scorer=ZipfScorer()
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
        word="rareword1",
        zipf_score=2.5,
        definition="(noun) definition 1",
        origin="origin 1",
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
    mock_dict_client.get_word_definition.return_value = (
        True,
        "(noun) test definition",
        "test origin",
    )

    pipeline = WordOfTheDayPipeline(
        stop_words={"the", "and"},
        dictionary_client=mock_dict_client,
        scorer=ZipfScorer(),
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

    def get_def_mock(word: str) -> tuple[bool, str, str | None]:
        if word == "rareword1":
            return True, "definition 1", "origin 1"
        if word == "rareword2":
            return False, "Not a valid English word.", None
        if word == "rareword3":
            return True, "definition 3", None
        return False, "Not found", None

    mock_dict_client.get_word_definition.side_effect = get_def_mock

    pipeline = WordOfTheDayPipeline(
        stop_words=set(), dictionary_client=mock_dict_client, scorer=ZipfScorer()
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


def test_pipeline_with_custom_scorer() -> None:
    """Verifies that injecting a custom WordScorer changes scoring and sorting."""

    class MockReverseScorer:
        @property
        def higher_is_better(self) -> bool:
            return True  # Sort descending (highest first)

        def score(self, word: str) -> float:
            # Score is word length
            return float(len(word))

    # "solitude" (8), "serendipity" (11)
    # Both are within default Zipf range (2.3 < score <= 4.0)
    mock_dict_client = MagicMock(spec=DictionaryClient)
    mock_dict_client.get_word_definition.return_value = (
        True,
        "mock definition",
        "mock origin",
    )

    pipeline = WordOfTheDayPipeline(
        stop_words=set(),
        dictionary_client=mock_dict_client,
        scorer=MockReverseScorer(),
    )

    candidates = pipeline.find_candidates("solitude serendipity", limit=2)

    # "serendipity" has length 11, "solitude" has length 8.
    # Because higher_is_better = True, "serendipity" (longest) should be sorted first.
    assert len(candidates) == 2
    assert candidates[0].word == "serendipity"
    assert candidates[0].score == 11.0
    assert candidates[1].word == "solitude"
    assert candidates[1].score == 8.0


def test_pipeline_find_candidates_with_reusable_callback() -> None:
    """Verifies that find_candidates applies the is_reusable_cb filter before scoring."""
    mock_dict_client = MagicMock(spec=DictionaryClient)
    mock_dict_client.get_word_definition.return_value = (
        True,
        "mock definition",
        "mock origin",
    )

    pipeline = WordOfTheDayPipeline(
        stop_words=set(),
        dictionary_client=mock_dict_client,
    )

    # We filter out "solitude"
    def is_reusable(word: str) -> bool:
        return word != "solitude"

    candidates = pipeline.find_candidates(
        "solitude serendipity", is_reusable_cb=is_reusable
    )

    # Only serendipity should remain and be checked/validated
    assert len(candidates) == 1
    assert candidates[0].word == "serendipity"
    # Verify we did NOT call Dictionary API for solitude
    mock_dict_client.get_word_definition.assert_called_once_with("serendipity")


def test_pipeline_clean_text_with_lemmatization() -> None:
    """Verifies that clean_text lemmatizes words when use_lemmatization is True."""
    pipeline = WordOfTheDayPipeline(stop_words=set(), use_lemmatization=True)
    cleaned = pipeline.clean_text("jumping cats ran")
    # "jumping" -> "jump", "cats" -> "cat", "ran" -> "run" (or "ran")
    assert "jump" in cleaned
    assert "cat" in cleaned
    assert "jumping" not in cleaned
    assert "cats" not in cleaned


def test_pipeline_clean_text_without_lemmatization() -> None:
    """Verifies that clean_text does not lemmatize words when use_lemmatization is False."""
    pipeline = WordOfTheDayPipeline(stop_words=set(), use_lemmatization=False)
    cleaned = pipeline.clean_text("jumping cats ran")
    assert "jumping" in cleaned
    assert "cats" in cleaned
    assert "jump" not in cleaned
    assert "cat" not in cleaned


def test_pipeline_lemmatization_and_stop_words() -> None:
    """Verifies that lemmatized words are correctly filtered by the stop words list."""
    # Stop word is the lemma form "jump"
    pipeline = WordOfTheDayPipeline(stop_words={"jump"}, use_lemmatization=True)
    cleaned = pipeline.clean_text("jumping cat")
    assert "cat" in cleaned
    assert "jump" not in cleaned
    assert "jumping" not in cleaned


def test_pipeline_tfidf_scorer_multiple_documents() -> None:
    """Verifies that the pipeline correctly uses TFIDFScorer on multiple documents."""
    mock_dict_client = MagicMock(spec=DictionaryClient)
    mock_dict_client.get_word_definition.return_value = (
        True,
        "test def",
        "test origin",
    )

    pipeline = WordOfTheDayPipeline(
        stop_words={"the", "and"},
        dictionary_client=mock_dict_client,
        use_lemmatization=True,
    )
    assert isinstance(pipeline.scorer, TFIDFScorer)

    documents = [
        "the cats were jumping on the roof",
        "and dogs were running in the garden",
    ]
    candidates = pipeline.find_candidates(documents, limit=8)
    # Both "cats/cat" and "dogs/dog" are nouns, should be extracted and validated
    assert len(candidates) >= 1
    words = {c.word for c in candidates}
    assert "cat" in words or "dog" in words


def test_pipeline_seen_words_cache_drops_invalid() -> None:
    """Verifies that the seen words cache filters out known invalid words early,
    preventing any dictionary API calls for them.
    """
    mock_dict_client = MagicMock(spec=DictionaryClient)
    mock_dict_client.get_word_definition.return_value = (True, "valid word", None)

    # Mock storage to return cached values
    mock_storage = MagicMock()

    # Mock get_cached_definition: "invalidword" is known to be invalid (False, ...)
    def get_cached_def(word: str):
        if word == "invalidword":
            return False, "Not a valid word", None
        return None

    mock_storage.get_cached_definition.side_effect = get_cached_def

    pipeline = WordOfTheDayPipeline(
        stop_words=set(),
        dictionary_client=mock_dict_client,
        storage=mock_storage,
    )

    # Run find_candidates with "invalidword" and "validword"
    # Note: "invalidword" should be dropped early by score_candidates because it is known invalid in the cache
    scored = pipeline.score_candidates(["invalidword validword"])

    # "invalidword" should not be in scored candidates because of the cache filter
    candidate_words = {w for w, _ in scored}
    assert "invalidword" not in candidate_words
    assert "validword" in candidate_words
