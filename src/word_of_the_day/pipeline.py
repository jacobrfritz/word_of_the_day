import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Self

from wordfreq import zipf_frequency

from .dictionary import DictionaryClient
from .logger import get_logger
from .scorers import WordScorer, ZipfScorer

if TYPE_CHECKING:
    from .storage import Storage

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
    score: float | None = None
    origin: str | None = None


class WordOfTheDayPipeline:
    """
    A pipeline to process a text corpus, extract and score unique words,
    and validate them using a dictionary client to select Word of the Day candidates.
    """

    def __init__(
        self,
        stop_words: set[str] | list[str] | Path | str | None = None,
        dictionary_client: DictionaryClient | None = None,
        scorer: WordScorer | None = None,
        storage: "Storage | None" = None,
    ) -> None:
        """
        Initialize the pipeline.

        Args:
            stop_words: A set/list of stop words, or a path to a file containing
                        them (one per line). If None, it tries to load
                        'stop_words.txt' from the project root.
            dictionary_client: An optional DictionaryClient instance. If not
                               provided, a default DictionaryClient will be created.
            scorer: An optional WordScorer instance to score candidates.
                    Defaults to ZipfScorer.
            storage: An optional Storage instance used to cache dictionary API
                     results. When provided, previously looked-up words are served
                     from the DB, skipping the network call entirely.
        """
        self.stop_words = self._load_stop_words(stop_words)
        self._external_client = dictionary_client is not None
        self.dictionary_client = dictionary_client or DictionaryClient(storage=storage)
        self.scorer = scorer or ZipfScorer()
        self.storage = storage

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
        Filters words within the Zipf frequency 'goldilocks' range, scores them
        using the configured scorer, and sorts them appropriately.
        """
        # Step 1: Pre-filter by Zipf score (goldilocks range) for efficiency
        filtered_words = []
        for word in words:
            z_score = zipf_frequency(word, "en")
            if min_score < z_score <= max_score:
                filtered_words.append(word)

        # Step 2: Score remaining words using the injected scorer
        if filtered_words:
            if hasattr(self.scorer, "score_batch"):
                scores = self.scorer.score_batch(filtered_words)
            else:
                scores = [self.scorer.score(word) for word in filtered_words]
            scored = list(zip(filtered_words, scores))
        else:
            scored = []

        # Step 3: Sort candidates based on scorer preference
        reverse = self.scorer.higher_is_better
        scored.sort(key=lambda item: item[1], reverse=reverse)
        return scored

    def validate_candidates(
        self,
        scored_candidates: list[tuple[str, float]],
        limit: int = 1,
    ) -> list[WordCandidate]:
        """
        Lazily validates scored candidates using the dictionary client.

        Walks through `scored_candidates` in order (highest score first) and
        calls the dictionary API only when needed — stopping as soon as `limit`
        valid words have been found.  Invalid words are skipped and never counted
        toward the limit.

        Results are cached in storage (when provided) so that repeat runs
        skip the network call for words already looked up.

        Args:
            scored_candidates: Words pre-sorted by score, best first.
            limit: Maximum number of *valid* words to return. Defaults to 1
                   so callers that only need one word pay for at most one API
                   call (or one cache hit).
        """
        validated_candidates: list[WordCandidate] = []

        for word, score in scored_candidates:
            if len(validated_candidates) >= limit:
                break

            # --- Cache lookup ---
            if self.storage is not None:
                is_valid, info, origin = self.dictionary_client.get_word_definition(
                    word, storage=self.storage
                )
            else:
                is_valid, info, origin = self.dictionary_client.get_word_definition(word)

            if is_valid:
                # If using standard ZipfScorer, the score *is* the zipf score.
                # Otherwise (e.g. EmbeddingScorer), we fetch the real Zipf score
                # for display and set the 'score' attribute to the similarity score.
                if isinstance(self.scorer, ZipfScorer):
                    zipf_val = score
                    custom_score = None
                else:
                    zipf_val = zipf_frequency(word, "en")
                    custom_score = score

                validated_candidates.append(
                    WordCandidate(
                        word=word,
                        zipf_score=zipf_val,
                        definition=info,
                        score=custom_score,
                        origin=origin,
                    )
                )
            else:
                logger.debug(f"Rejected word '{word}' ({score:.2f}): {info}")

        return validated_candidates

    def score_candidates(
        self,
        text: str,
        min_score: float = 2.3,
        max_score: float = 4.0,
        shuffle: bool = False,
        is_reusable_cb: Callable[[str], bool] | None = None,
    ) -> list[tuple[str, float]]:
        """
        Phase 1 of the pipeline: extract, filter, and score words from the corpus.

        No dictionary API calls are made here. Returns all scored candidates
        sorted best-first so the caller can drive validation lazily.

        Args:
            text: Raw text corpus to mine for candidate words.
            min_score: Minimum Zipf frequency (exclusive).
            max_score: Maximum Zipf frequency (inclusive).
            shuffle: If True, randomise order after scoring (useful for
                     exploration; disables best-first ordering).
            is_reusable_cb: Optional callback that returns True if a word is
                            eligible for selection (e.g. not used in 365 days).
                            Words that return False are excluded before scoring.
        """
        unique_words = self.clean_text(text)
        if is_reusable_cb:
            unique_words = {w for w in unique_words if is_reusable_cb(w)}
        scored = self.score_and_filter(
            unique_words, min_score=min_score, max_score=max_score
        )
        if shuffle:
            import random

            random.shuffle(scored)
        return scored

    def find_candidates(
        self,
        text: str,
        min_score: float = 2.3,
        max_score: float = 4.0,
        limit: int = 1,
        shuffle: bool = False,
        is_reusable_cb: Callable[[str], bool] | None = None,
    ) -> list[WordCandidate]:
        """
        Convenience wrapper: score the corpus then lazily validate.

        Calls `score_candidates` (no API) then `validate_candidates` (API on
        demand), stopping as soon as `limit` valid words are found.

        Args:
            text: Raw text corpus.
            min_score: Minimum Zipf frequency (exclusive).
            max_score: Maximum Zipf frequency (inclusive).
            limit: Maximum number of valid words to return. Defaults to 1 —
                   callers that only need one word never pay for more than one
                   API call.
            shuffle: Randomise candidate order before validation.
            is_reusable_cb: Optional reusability gate applied before scoring.
        """
        scored = self.score_candidates(
            text,
            min_score=min_score,
            max_score=max_score,
            shuffle=shuffle,
            is_reusable_cb=is_reusable_cb,
        )
        return self.validate_candidates(scored, limit=limit)

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
