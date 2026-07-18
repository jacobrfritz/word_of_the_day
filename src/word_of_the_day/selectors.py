from dataclasses import dataclass
from typing import Protocol
import numpy as np


@dataclass
class ScoredWord:
    word: str
    score: float


class WordSelector(Protocol):
    def select(self, candidates: list[ScoredWord]) -> str:
        """Selects a single word from a list of scored candidates."""
        ...


class HighestScoreSelector:
    """
    Selects the word with the highest (or lowest, if higher_is_better=False) score.
    """

    def __init__(self, higher_is_better: bool = True) -> None:
        self.higher_is_better = higher_is_better

    def select(self, candidates: list[ScoredWord]) -> str:
        if not candidates:
            raise ValueError("Candidate list cannot be empty")

        if self.higher_is_better:
            return max(candidates, key=lambda c: c.score).word
        else:
            return min(candidates, key=lambda c: c.score).word


class TemperatureSoftmaxSelector:
    """
    Selects a word based on a Softmax probability distribution of their scores,
    scaled by a temperature parameter.
    """

    def __init__(self, temperature: float = 1.0, higher_is_better: bool = True) -> None:
        # Prevent division by zero; clamp to a small positive float
        self.temperature = max(float(temperature), 1e-6)
        self.higher_is_better = higher_is_better

    def select(self, candidates: list[ScoredWord]) -> str:
        if not candidates:
            raise ValueError("Candidate list cannot be empty")

        words = [c.word for c in candidates]
        scores = np.array([c.score for c in candidates], dtype=np.float64)

        # If lower scores are better, negate scores so that lower scores get higher probabilities
        if not self.higher_is_better:
            scores = -scores

        # Scale by temperature and shift for numerical stability
        scaled_scores = scores / self.temperature
        shifted_scores = scaled_scores - np.max(scaled_scores)

        exp_scores = np.exp(shifted_scores)
        probabilities = exp_scores / np.sum(exp_scores)

        # Standardize probability to sum to exactly 1.0 (to avoid rounding errors in np.random.choice)
        probabilities = probabilities / np.sum(probabilities)

        return str(np.random.choice(words, p=probabilities))
