import re
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self

from wordfreq import zipf_frequency

from .dictionary import DictionaryClient
from .logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class WordCandidate:
    """
    Represents a candidate word for the Word of the Day,
    including its Zipf score and validated definition.
    """

    word: str
    zipf_score: float
    definition: str


class WordOfTheDayPipeline:
    """
    A pipeline to process a text corpus, extract and score unique words,
    and validate them using a dictionary client to select Word of the Day candidates.
    """

    def __init__(
        self,
        stop_words: set[str] | list[str] | Path | str | None = None,
        dictionary_client: DictionaryClient | None = None,
    ) -> None:
        """
        Initialize the pipeline.

        Args:
            stop_words: A set/list of stop words, or a path to a file containing
                        them (one per line). If None, it tries to load
                        'stop_words.txt' from the project root.
            dictionary_client: An optional DictionaryClient instance. If not
                               provided, a default DictionaryClient will be created.
        """
        self.stop_words = self._load_stop_words(stop_words)
        self._external_client = dictionary_client is not None
        self.dictionary_client = dictionary_client or DictionaryClient()

    def _load_stop_words(
        self, stop_words: set[str] | list[str] | Path | str | None
    ) -> set[str]:
        """Resolves and loads stop words into a lowercase set."""
        if isinstance(stop_words, set):
            return {w.lower() for w in stop_words}
        if isinstance(stop_words, list):
            return {w.lower() for w in stop_words}

        path_to_load = None
        if isinstance(stop_words, str | Path):
            path_to_load = Path(stop_words)
        elif stop_words is None:
            # Try to resolve stop_words.txt relative to this file
            # src/word_of_the_day/pipeline.py -> project root is 3 levels up
            pkg_root_stop_words = (
                Path(__file__).resolve().parent.parent.parent / "stop_words.txt"
            )
            if pkg_root_stop_words.exists():
                path_to_load = pkg_root_stop_words
            else:
                # Check current working directory
                cwd_stop_words = Path("stop_words.txt")
                if cwd_stop_words.exists():
                    path_to_load = cwd_stop_words

        if path_to_load and path_to_load.exists():
            try:
                content = path_to_load.read_text(encoding="utf-8")
                return {
                    word.lower().strip() for word in content.split() if word.strip()
                }
            except Exception as e:
                logger.error(f"Failed to load stop words from {path_to_load}: {e}")

        logger.warning("No stop words loaded. Pipeline will run without stop words.")
        return set()

    def clean_text(self, text: str) -> set[str]:
        """
        Extract unique cleaned words from the text corpus, filtering out punctuation
        and stop words.
        """
        raw_words = text.lower().split()
        clean_pattern = r"[^a-zA-Z\-'’]"
        processed_words = set()

        for word in raw_words:
            cleaned = re.sub(clean_pattern, "", word)
            # Drop empty strings or single leftover hyphens/apostrophes
            if (
                cleaned
                and re.match(r"^[a-z\-'’]+$", cleaned)
                and cleaned not in self.stop_words
            ):
                processed_words.add(cleaned)

        return processed_words

    def score_and_filter(
        self,
        words: set[str],
        min_score: float = 2.3,
        max_score: float = 4.0,
    ) -> list[tuple[str, float]]:
        """
        Scores the words using Zipf frequency, filters them within the 'goldilocks'
        range, and sorts them ascending (rarest first).
        """
        scored = []
        for word in words:
            score = zipf_frequency(word, "en")
            if min_score < score <= max_score:
                scored.append((word, score))

        # Sort by score ascending (rarest first)
        scored.sort(key=lambda item: item[1])
        return scored

    def validate_candidates(
        self,
        scored_candidates: list[tuple[str, float]],
        limit: int = 15,
    ) -> list[WordCandidate]:
        """
        Validates candidates using the dictionary client, continuing until
        the limit of valid words is reached.
        """
        validated_candidates: list[WordCandidate] = []

        for word, score in scored_candidates:
            if len(validated_candidates) >= limit:
                break
            is_valid, info = self.dictionary_client.get_word_definition(word)
            if is_valid:
                validated_candidates.append(
                    WordCandidate(word=word, zipf_score=score, definition=info)
                )
            else:
                logger.debug(f"Rejected word '{word}' ({score:.2f}): {info}")

        return validated_candidates

    def find_candidates(
        self,
        text: str,
        min_score: float = 2.3,
        max_score: float = 4.0,
        limit: int = 15,
        shuffle: bool = False,
    ) -> list[WordCandidate]:
        """
        Run the complete pipeline on the provided text corpus.
        """
        unique_words = self.clean_text(text)
        scored_candidates = self.score_and_filter(
            unique_words, min_score=min_score, max_score=max_score
        )
        if shuffle:
            import random

            random.shuffle(scored_candidates)
        return self.validate_candidates(scored_candidates, limit=limit)

    def close(self) -> None:
        """Close the underlying dictionary client session.

        Only closes if the client was created internally.
        """
        if not self._external_client:
            self.dictionary_client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
