# src/word_of_the_day/__init__.py
from .dictionary import DictionaryClient
from .generator import WordSourceGenerator
from .logger import get_logger, setup_logging
from .pipeline import WordCandidate, WordOfTheDayPipeline
from .scorers import CompositeScorer, EmbeddingScorer, WordScorer, ZipfScorer

__all__ = [
    "setup_logging",
    "get_logger",
    "DictionaryClient",
    "WordSourceGenerator",
    "WordCandidate",
    "WordOfTheDayPipeline",
    "WordScorer",
    "ZipfScorer",
    "EmbeddingScorer",
    "CompositeScorer",
]
