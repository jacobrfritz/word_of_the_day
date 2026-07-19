import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Self

import nltk
from wordfreq import zipf_frequency

from .config import settings
from .dictionary import DictionaryClient
from .logger import get_logger
from .scorers import TFIDFScorer, WordScorer, ZipfScorer
from .selectors import (
    HighestScoreSelector,
    TemperatureSoftmaxSelector,
    WordSelector,
)
from .utils import ensure_nltk_resources

if TYPE_CHECKING:
    from .storage import Storage

logger = get_logger(__name__)


try:
    import simplemma

    HAS_SIMPLEMMA = True
except ImportError:
    HAS_SIMPLEMMA = False


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
        use_lemmatization: bool = True,
        selector: WordSelector | None = None,
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
                    Defaults to TFIDFScorer.
            storage: An optional Storage instance used to cache dictionary API
                     results. When provided, previously looked-up words are served
                     from the DB, skipping the network call entirely.
            selector: An optional WordSelector instance to select the final word.
        """
        self.stop_words = self._load_stop_words(stop_words)
        self._external_client = dictionary_client is not None
        self.dictionary_client = dictionary_client or DictionaryClient(storage=storage)
        self.scorer = scorer or TFIDFScorer(stop_words=self.stop_words)
        if isinstance(self.scorer, TFIDFScorer):
            self.scorer.stop_words = self.stop_words
        self.storage = storage
        if use_lemmatization and not HAS_SIMPLEMMA:
            logger.warning("simplemma is not installed. Skipping lemmatization.")
            self.use_lemmatization = False
        else:
            self.use_lemmatization = use_lemmatization

        # Initialize WordSelector
        if selector is None:
            if settings.selection_strategy == "softmax":
                self.selector = TemperatureSoftmaxSelector(
                    temperature=settings.selection_temperature,
                    higher_is_better=self.scorer.higher_is_better,
                )
            else:
                self.selector = HighestScoreSelector(
                    higher_is_better=self.scorer.higher_is_better,
                )
        else:
            self.selector = selector

        logger.info(
            f"Initialized WordOfTheDayPipeline (lemmatization={'enabled' if self.use_lemmatization else 'disabled'})."
        )

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
        raw_cleaned_unique: set[str] = set()

        for word in raw_words:
            cleaned = re.sub(clean_pattern, "", word)
            # Drop empty strings or single leftover hyphens/apostrophes
            if cleaned and re.match(r"^[a-z\-'’]+$", cleaned):
                if self.use_lemmatization:
                    raw_cleaned_unique.add(cleaned)
                    lemma = simplemma.lemmatize(cleaned, lang="en")
                    if lemma not in self.stop_words:
                        processed_words.add(lemma)
                else:
                    if cleaned not in self.stop_words:
                        processed_words.add(cleaned)

        if self.use_lemmatization:
            logger.info(
                f"Lemmatization completed: reduced {len(raw_cleaned_unique)} unique cleaned words "
                f"to {len(processed_words)} unique lemmas (excluding stop words)."
            )
        else:
            logger.info(
                f"Cleaning completed: extracted {len(processed_words)} unique words (excluding stop words)."
            )

        return processed_words

    def clean_document(self, text: str) -> str:
        """
        Cleans a document by lowercasing, removing punctuation, filtering stop words,
        and optionally lemmatizing, returning a space-separated string of tokens.
        """
        raw_words = text.lower().split()
        clean_pattern = r"[^a-zA-Z\-'’]"
        processed_tokens = []

        for word in raw_words:
            cleaned = re.sub(clean_pattern, "", word)
            # Drop empty strings or single leftover hyphens/apostrophes
            if cleaned and re.match(r"^[a-z\-'’]+$", cleaned):
                if self.use_lemmatization and HAS_SIMPLEMMA:
                    lemma = simplemma.lemmatize(cleaned, lang="en")
                    if lemma not in self.stop_words:
                        processed_tokens.append(lemma)
                else:
                    if cleaned not in self.stop_words:
                        processed_tokens.append(cleaned)
        return " ".join(processed_tokens)

    def score_and_filter(
        self,
        words: set[str],
        min_score: float | None = None,
        max_score: float | None = None,
        min_word_length: int | None = None,
        max_word_length: int | None = None,
        pos_filter_nouns: bool | None = None,
        pos_filter_adjectives: bool | None = None,
        pos_filter_verbs: bool | None = None,
    ) -> list[tuple[str, float]]:
        """
        Filters words using Part-of-Speech (POS) tagging and length bounds,
        scores them using the configured scorer, and sorts them appropriately.
        """
        if not words:
            return []

        # Step 1: Pre-filter by POS tagging and word length
        ensure_nltk_resources()
        word_list = sorted(words)
        try:
            tagged_words = nltk.pos_tag(word_list, tagset="universal")
        except Exception as e:
            logger.error(f"POS tagging failed: {e}. Defaulting to empty list.")
            tagged_words = []

        # Resolve parameters falling back to settings
        nouns = (
            pos_filter_nouns
            if pos_filter_nouns is not None
            else settings.pos_filter_nouns
        )
        adjectives = (
            pos_filter_adjectives
            if pos_filter_adjectives is not None
            else settings.pos_filter_adjectives
        )
        verbs = (
            pos_filter_verbs
            if pos_filter_verbs is not None
            else settings.pos_filter_verbs
        )
        min_len = (
            min_word_length if min_word_length is not None else settings.min_word_length
        )
        max_len = (
            max_word_length if max_word_length is not None else settings.max_word_length
        )

        allowed_tags = set()
        if nouns:
            allowed_tags.add("NOUN")
        if adjectives:
            allowed_tags.add("ADJ")
        if verbs:
            allowed_tags.add("VERB")

        filtered_words = []
        for word, tag in tagged_words:
            # Length filter
            if min_len is not None and len(word) < min_len:
                continue
            if max_len is not None and len(word) > max_len:
                continue

            # POS filter
            if tag not in allowed_tags:
                continue

            # Zipf score filter (goldilocks range)
            z_score = zipf_frequency(word, "en")
            if min_score is not None and z_score <= min_score:
                continue
            if max_score is not None and z_score > max_score:
                continue

            filtered_words.append(word)

        # Step 2: Score remaining words using the injected scorer
        if filtered_words:
            if hasattr(self.scorer, "score_batch"):
                scores = self.scorer.score_batch(filtered_words)
            else:
                scores = [self.scorer.score(word) for word in filtered_words]
            scored = list(zip(filtered_words, scores, strict=False))
        else:
            scored = []

        # Step 3: Sort candidates based on scorer preference
        reverse = self.scorer.higher_is_better
        scored.sort(key=lambda item: item[1], reverse=reverse)
        return scored

    def validate_candidates(
        self,
        scored_candidates: list[tuple[str, float]] | list[tuple[str, str, float]],
        limit: int = 1,
        pos_filter_nouns: bool | None = None,
        pos_filter_adjectives: bool | None = None,
        pos_filter_verbs: bool | None = None,
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
            scored_candidates: Words pre-sorted by score (with optional source), best first.
            limit: Maximum number of *valid* words to return. Defaults to 1
                   so callers that only need one word pay for at most one API
                   call (or one cache hit).
        """
        validated_candidates: list[WordCandidate] = []
        cache_updates = []

        for item in scored_candidates:
            if len(validated_candidates) >= limit:
                break

            if len(item) == 3:
                source, word, score = item  # type: ignore
            else:
                word, score = item  # type: ignore
                source = None

            if source and source.startswith("db:"):
                source = source[3:]

            # --- Cache lookup ---
            kwargs = {}
            if source is not None:
                kwargs["source"] = source
            if self.storage is not None:
                kwargs["storage"] = self.storage

            is_valid, info, origin = self.dictionary_client.get_word_definition(
                word, **kwargs
            )

            # Record for bulk save
            cache_updates.append({"word": word, "is_valid": is_valid})

            if is_valid:
                # POS post-validation check
                if (
                    pos_filter_nouns is not None
                    or pos_filter_adjectives is not None
                    or pos_filter_verbs is not None
                ):
                    nouns = (
                        pos_filter_nouns
                        if pos_filter_nouns is not None
                        else settings.pos_filter_nouns
                    )
                    adjectives = (
                        pos_filter_adjectives
                        if pos_filter_adjectives is not None
                        else settings.pos_filter_adjectives
                    )
                    verbs = (
                        pos_filter_verbs
                        if pos_filter_verbs is not None
                        else settings.pos_filter_verbs
                    )

                    # If we are restricting POS (i.e. not all are True)
                    if not (nouns and adjectives and verbs):
                        pos_match = re.match(r"^\(([^)]+)\)\s*(.*)", info)
                        dict_pos = (
                            pos_match.group(1).lower().strip() if pos_match else None
                        )
                        if dict_pos:
                            is_noun = "noun" in dict_pos
                            is_adj = "adj" in dict_pos
                            is_verb = "verb" in dict_pos

                            allowed = False
                            if nouns and is_noun:
                                allowed = True
                            if adjectives and is_adj:
                                allowed = True
                            if verbs and is_verb:
                                allowed = True

                            if not allowed:
                                logger.debug(
                                    f"Skipped word '{word}' ({score:.2f}) because dictionary POS "
                                    f"'{dict_pos}' does not match target POS filters "
                                    f"(nouns={nouns}, adjectives={adjectives}, verbs={verbs})."
                                )
                                continue

                # If using standard ZipfScorer, the score *is* the zipf score.
                # Otherwise (e.g. EmbeddingScorer/TFIDFScorer), we fetch the real Zipf score
                # for display and set the 'score' attribute to the similarity/TF-IDF score.
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

        if self.storage is not None and cache_updates:
            self.storage.bulk_save_seen_words(cache_updates)

        return validated_candidates

    def score_candidates(
        self,
        text: str | list[str],
        min_score: float | None = None,
        max_score: float | None = None,
        shuffle: bool = False,
        is_reusable_cb: Callable[[str], bool] | None = None,
        min_word_length: int | None = None,
        max_word_length: int | None = None,
        pos_filter_nouns: bool | None = None,
        pos_filter_adjectives: bool | None = None,
        pos_filter_verbs: bool | None = None,
    ) -> list[tuple[str, float]]:
        """
        Phase 1 of the pipeline: extract, filter, and score words from the corpus.

        Supports both raw text (str) and lists of documents (list[str]).
        If TFIDFScorer is used, fits on the documents and filters candidates.
        """
        if isinstance(self.scorer, TFIDFScorer):
            documents = [text] if isinstance(text, str) else text
            cleaned_docs = [self.clean_document(doc) for doc in documents]
            # TFIDFScorer returns list of (word, score)
            top_scored = self.scorer.get_top_words_with_scores(cleaned_docs, limit=500)

            # Filter by POS and word length
            ensure_nltk_resources()
            word_list = sorted([w for w, _ in top_scored])
            try:
                tagged_words = nltk.pos_tag(word_list, tagset="universal")
            except Exception as e:
                logger.error(f"POS tagging failed: {e}. Defaulting to empty list.")
                tagged_words = []

            # Resolve parameters falling back to settings
            nouns = (
                pos_filter_nouns
                if pos_filter_nouns is not None
                else settings.pos_filter_nouns
            )
            adjectives = (
                pos_filter_adjectives
                if pos_filter_adjectives is not None
                else settings.pos_filter_adjectives
            )
            verbs = (
                pos_filter_verbs
                if pos_filter_verbs is not None
                else settings.pos_filter_verbs
            )
            min_len = (
                min_word_length
                if min_word_length is not None
                else settings.min_word_length
            )
            max_len = (
                max_word_length
                if max_word_length is not None
                else settings.max_word_length
            )

            allowed_tags = set()
            if nouns:
                allowed_tags.add("NOUN")
            if adjectives:
                allowed_tags.add("ADJ")
            if verbs:
                allowed_tags.add("VERB")

            valid_words = set()
            for word, tag in tagged_words:
                if min_len is not None and len(word) < min_len:
                    continue
                if max_len is not None and len(word) > max_len:
                    continue
                if tag not in allowed_tags:
                    continue

                # Zipf score filter (goldilocks range)
                z_score = zipf_frequency(word, "en")
                if min_score is not None and z_score <= min_score:
                    continue
                if max_score is not None and z_score > max_score:
                    continue

                valid_words.add(word)

            # Compile final scored candidates (preserving sorted TF-IDF order)
            scored = []
            for word, score in top_scored:
                if word not in valid_words:
                    continue
                if is_reusable_cb and not is_reusable_cb(word):
                    continue
                if self.storage is not None:
                    cached = self.storage.get_cached_definition(word)
                    if cached is not None:
                        is_valid_cached, _, _ = cached
                        if not is_valid_cached:
                            # Skip known invalid words
                            continue
                scored.append((word, score))
        else:
            aggregate_text = "\n\n".join(text) if isinstance(text, list) else text
            unique_words = self.clean_text(aggregate_text)
            if is_reusable_cb:
                unique_words = {w for w in unique_words if is_reusable_cb(w)}
            scored = self.score_and_filter(
                unique_words,
                min_score=min_score,
                max_score=max_score,
                min_word_length=min_word_length,
                max_word_length=max_word_length,
                pos_filter_nouns=pos_filter_nouns,
                pos_filter_adjectives=pos_filter_adjectives,
                pos_filter_verbs=pos_filter_verbs,
            )

        if shuffle:
            import random

            random.shuffle(scored)
        return scored

    def find_candidates(
        self,
        text: str | list[str],
        min_score: float | None = None,
        max_score: float | None = None,
        limit: int = 1,
        shuffle: bool = False,
        is_reusable_cb: Callable[[str], bool] | None = None,
        min_word_length: int | None = None,
        max_word_length: int | None = None,
        pos_filter_nouns: bool | None = None,
        pos_filter_adjectives: bool | None = None,
        pos_filter_verbs: bool | None = None,
    ) -> list[WordCandidate]:
        """
        Convenience wrapper: score the corpus then lazily validate.

        Calls `score_candidates` then `validate_candidates`, stopping as soon
        as `limit` valid words are found.
        """
        scored = self.score_candidates(
            text,
            min_score=min_score,
            max_score=max_score,
            shuffle=shuffle,
            is_reusable_cb=is_reusable_cb,
            min_word_length=min_word_length,
            max_word_length=max_word_length,
            pos_filter_nouns=pos_filter_nouns,
            pos_filter_adjectives=pos_filter_adjectives,
            pos_filter_verbs=pos_filter_verbs,
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
