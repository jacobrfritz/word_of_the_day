from unittest.mock import patch
import numpy as np
import pytest

from word_of_the_day.selectors import (
    HighestScoreSelector,
    ScoredWord,
    TemperatureSoftmaxSelector,
)


def test_highest_score_selector_higher_is_better() -> None:
    """Verifies that HighestScoreSelector picks highest score when higher_is_better=True."""
    selector = HighestScoreSelector(higher_is_better=True)
    candidates = [
        ScoredWord(word="apple", score=1.5),
        ScoredWord(word="banana", score=4.5),
        ScoredWord(word="cherry", score=3.0),
    ]
    assert selector.select(candidates) == "banana"


def test_highest_score_selector_lower_is_better() -> None:
    """Verifies that HighestScoreSelector picks lowest score when higher_is_better=False."""
    selector = HighestScoreSelector(higher_is_better=False)
    candidates = [
        ScoredWord(word="apple", score=1.5),
        ScoredWord(word="banana", score=4.5),
        ScoredWord(word="cherry", score=3.0),
    ]
    assert selector.select(candidates) == "apple"


def test_highest_score_selector_empty_list() -> None:
    """Verifies that HighestScoreSelector raises ValueError when candidates is empty."""
    selector = HighestScoreSelector()
    with pytest.raises(ValueError, match="Candidate list cannot be empty"):
        selector.select([])


def test_softmax_selector_zero_negative_temperature() -> None:
    """Verifies that the constructor clamps temperature to at least 1e-6."""
    selector_zero = TemperatureSoftmaxSelector(temperature=0.0)
    assert selector_zero.temperature == 1e-6

    selector_neg = TemperatureSoftmaxSelector(temperature=-5.0)
    assert selector_neg.temperature == 1e-6


def test_softmax_selector_empty_list() -> None:
    """Verifies that TemperatureSoftmaxSelector raises ValueError when candidates is empty."""
    selector = TemperatureSoftmaxSelector()
    with pytest.raises(ValueError, match="Candidate list cannot be empty"):
        selector.select([])


def test_softmax_selector_numerical_stability() -> None:
    """Ensures TemperatureSoftmaxSelector does not raise warnings/errors on huge/small scores."""
    selector = TemperatureSoftmaxSelector(temperature=1.0)
    candidates = [
        ScoredWord(word="huge", score=1e10),
        ScoredWord(word="tiny", score=-1e10),
        ScoredWord(word="normal", score=1.0),
    ]
    # This should not raise overflow or division warnings/errors
    chosen = selector.select(candidates)
    assert chosen in ["huge", "tiny", "normal"]


def test_softmax_selector_probability_distribution() -> None:
    """Asserts that high temperature approaches uniform distribution using np.random.choice mock."""
    selector = TemperatureSoftmaxSelector(temperature=100.0, higher_is_better=True)
    candidates = [
        ScoredWord(word="a", score=10.0),
        ScoredWord(word="b", score=1.0),
    ]

    with patch("numpy.random.choice") as mock_choice:
        mock_choice.return_value = "b"
        selector.select(candidates)
        
        mock_choice.assert_called_once()
        args, kwargs = mock_choice.call_args
        
        # Check targets and probabilities
        assert args[0] == ["a", "b"]
        probs = kwargs["p"]
        # With very high temp, probabilities should be close to 0.5 each
        np.testing.assert_allclose(probs, [0.5, 0.5], atol=0.05)


def test_softmax_selector_deterministic_fallback() -> None:
    """Asserts that very low temperature (e.g. near 0) acts like HighestScoreSelector."""
    # Clamped to 1e-6
    selector = TemperatureSoftmaxSelector(temperature=1e-6, higher_is_better=True)
    candidates = [
        ScoredWord(word="a", score=1.0),
        ScoredWord(word="best", score=5.0),
        ScoredWord(word="b", score=2.0),
    ]
    # Probabilities should concentrate fully on "best"
    for _ in range(10):
        assert selector.select(candidates) == "best"


def test_softmax_selector_lower_is_better() -> None:
    """Asserts that lower_is_better=False correctly shifts probabilities to favor lower scores."""
    selector = TemperatureSoftmaxSelector(temperature=1e-6, higher_is_better=False)
    candidates = [
        ScoredWord(word="best", score=1.0),
        ScoredWord(word="a", score=5.0),
        ScoredWord(word="b", score=2.0),
    ]
    # Should pick "best" (lowest score) deterministically
    for _ in range(10):
        assert selector.select(candidates) == "best"
