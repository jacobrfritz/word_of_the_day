# tests/test_pos_alternation.py
from unittest.mock import MagicMock

from word_of_the_day.utils.pos import get_target_pos_for_date


def test_pos_alternation_empty_history():
    # When history is empty, target POS should default to "noun"
    mock_storage = MagicMock()
    mock_storage.get_history.return_value = []

    assert get_target_pos_for_date(mock_storage, "2026-07-19") == "noun"


def test_pos_alternation_noun_to_adjective():
    # If the last word was a noun, next should be adjective
    mock_storage = MagicMock()
    mock_storage.get_history.return_value = [
        {
            "date": "2026-07-18",
            "word": "apple",
            "definition": "(noun) A round fruit.",
            "source": "test",
            "score": 3.0,
            "extra_info": None,
            "origin": None,
            "cluster_id": None,
        }
    ]

    assert get_target_pos_for_date(mock_storage, "2026-07-19") == "adjective"


def test_pos_alternation_adjective_to_verb():
    # If the last word was an adjective, next should be verb
    mock_storage = MagicMock()
    mock_storage.get_history.return_value = [
        {
            "date": "2026-07-18",
            "word": "red",
            "definition": "(adjective) Of color red.",
            "source": "test",
            "score": 3.0,
            "extra_info": None,
            "origin": None,
            "cluster_id": None,
        }
    ]

    assert get_target_pos_for_date(mock_storage, "2026-07-19") == "verb"


def test_pos_alternation_verb_to_noun():
    # If the last word was a verb, next should be noun
    mock_storage = MagicMock()
    mock_storage.get_history.return_value = [
        {
            "date": "2026-07-18",
            "word": "run",
            "definition": "(verb) To move fast.",
            "source": "test",
            "score": 3.0,
            "extra_info": None,
            "origin": None,
            "cluster_id": None,
        }
    ]

    assert get_target_pos_for_date(mock_storage, "2026-07-19") == "noun"


def test_pos_alternation_ignores_future_dates():
    # History contains a date after or equal to target date; it should be ignored.
    mock_storage = MagicMock()
    mock_storage.get_history.return_value = [
        {
            "date": "2026-07-20",
            "word": "run",
            "definition": "(verb) To move fast.",
            "source": "test",
            "score": 3.0,
            "extra_info": None,
            "origin": None,
            "cluster_id": None,
        },
        {
            "date": "2026-07-18",
            "word": "apple",
            "definition": "(noun) A fruit.",
            "source": "test",
            "score": 3.0,
            "extra_info": None,
            "origin": None,
            "cluster_id": None,
        },
    ]

    # Target date is 2026-07-19. The verb on 2026-07-20 is in the future, so the last POS before 2026-07-19 is noun, which rotates to adjective.
    assert get_target_pos_for_date(mock_storage, "2026-07-19") == "adjective"


def test_pos_alternation_skips_unrecognized():
    # Unrecognized tags should be skipped, looking at the next most recent
    mock_storage = MagicMock()
    mock_storage.get_history.return_value = [
        {
            "date": "2026-07-18",
            "word": "blah",
            "definition": "(unknown) Not a word.",
            "source": "test",
            "score": 3.0,
            "extra_info": None,
            "origin": None,
            "cluster_id": None,
        },
        {
            "date": "2026-07-17",
            "word": "red",
            "definition": "(adjective) Of color red.",
            "source": "test",
            "score": 3.0,
            "extra_info": None,
            "origin": None,
            "cluster_id": None,
        },
    ]

    assert get_target_pos_for_date(mock_storage, "2026-07-19") == "verb"


def test_validate_candidates_with_pos_filtering():
    from word_of_the_day.pipeline import WordOfTheDayPipeline
    from word_of_the_day.scorers import ZipfScorer

    # Mock the dictionary client to return specific definitions
    mock_dict_client = MagicMock()
    mock_dict_client.get_word_definition.side_effect = lambda word, **kwargs: {
        "apple": (True, "(noun) A fruit.", "eng"),
        "run": (True, "(verb) To sprint.", "eng"),
        "red": (True, "(adjective) Colored.", "eng"),
    }[word]

    pipeline = WordOfTheDayPipeline(
        stop_words=set(),
        dictionary_client=mock_dict_client,
        scorer=ZipfScorer(),
        use_lemmatization=False,
    )

    candidates = [("apple", 4.0), ("run", 3.5), ("red", 3.0)]

    # Case 1: Filter to ONLY noun
    res = pipeline.validate_candidates(
        candidates,
        limit=5,
        pos_filter_nouns=True,
        pos_filter_adjectives=False,
        pos_filter_verbs=False,
    )
    assert len(res) == 1
    assert res[0].word == "apple"

    # Case 2: Filter to ONLY verb
    res = pipeline.validate_candidates(
        candidates,
        limit=5,
        pos_filter_nouns=False,
        pos_filter_adjectives=False,
        pos_filter_verbs=True,
    )
    assert len(res) == 1
    assert res[0].word == "run"

    # Case 3: Filter to ONLY adjective
    res = pipeline.validate_candidates(
        candidates,
        limit=5,
        pos_filter_nouns=False,
        pos_filter_adjectives=True,
        pos_filter_verbs=False,
    )
    assert len(res) == 1
    assert res[0].word == "red"
