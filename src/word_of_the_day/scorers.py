import csv
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from wordfreq import zipf_frequency

from .logger import get_logger

logger = get_logger(__name__)


@runtime_checkable
class WordScorer(Protocol):
    """
    Protocol defining the interface for a word scorer.
    """

    @property
    def higher_is_better(self) -> bool:
        """
        Indicates if higher scores are better (True) or lower scores are better (False).
        """
        ...

    def score(self, word: str) -> float:
        """
        Score a word. Higher scores indicate more suitable candidates.

        Args:
            word: The word to score.

        Returns:
            A float score.
        """
        ...


class ZipfScorer:
    """
    Scores words using their Zipf frequency score.
    """

    def __init__(self, lang: str = "en") -> None:
        self.lang = lang

    @property
    def higher_is_better(self) -> bool:
        # Zipf frequency score: rarer words (lower score) are better for Word of the Day
        return False

    def score(self, word: str) -> float:
        """
        Returns the Zipf frequency score of the word.
        """
        return zipf_frequency(word, self.lang)


class EmbeddingScorer:
    """
    Scores words using K-Nearest Neighbors (KNN) cosine similarity
    against a golden seed list of Word of the Day vocabulary.
    """

    def __init__(
        self,
        seed_csv_path: str | Path,
        cache_npz_path: str | Path,
        model_name: str = "all-MiniLM-L6-v2",
        k: int = 5,
    ) -> None:
        self.seed_csv_path = Path(seed_csv_path)
        self.cache_npz_path = Path(cache_npz_path)
        self.model_name = model_name
        self.k = k

        # Check dependencies
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer

            self._np = np
            self._transformer_class = SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "EmbeddingScorer requires 'sentence-transformers' "
                "and 'numpy' packages. Please install them using: "
                "uv pip install sentence-transformers numpy"
            ) from e

        self.seed_words: list[str] = []
        self.seed_embeddings: np.ndarray = np.empty((0, 0))
        self.normalized_seeds: np.ndarray = np.empty((0, 0))
        self.model: Any = None

        self._initialize()

    @property
    def higher_is_better(self) -> bool:
        # Cosine similarity: closer to seed words (higher similarity) is better
        return True

    def _initialize(self) -> None:
        """Loads or precomputes the seed word embeddings."""
        if not self.cache_npz_path.exists():
            if not self.seed_csv_path.exists():
                raise FileNotFoundError(
                    f"Neither the embedding cache ({self.cache_npz_path}) nor "
                    f"the seed CSV file ({self.seed_csv_path}) was found."
                )
            self._compile_cache()
        else:
            self._load_cache()

    def _load_cache(self) -> None:
        """Loads cached embeddings from the npz file."""
        logger.info(f"Loading seed word embeddings cache from {self.cache_npz_path}")
        np = self._np
        try:
            data = np.load(self.cache_npz_path, allow_pickle=True)
            self.seed_words = [str(w) for w in data["words"]]
            self.seed_embeddings = data["embeddings"]

            # L2-normalize the seed embeddings for fast cosine similarity dot products
            norms = np.linalg.norm(self.seed_embeddings, axis=1, keepdims=True)
            # Avoid division by zero
            norms[norms == 0] = 1.0
            self.normalized_seeds = self.seed_embeddings / norms
            logger.info(f"Loaded {len(self.seed_words)} precomputed embeddings.")
        except Exception as e:
            logger.error(f"Failed to load embedding cache: {e}. Recompiling...")
            self._compile_cache()

    def _compile_cache(self) -> None:
        """Compiles the seed word CSV into a cached npz file."""
        logger.info(f"Compiling seed embeddings from {self.seed_csv_path}")
        np = self._np

        # Read words from CSV
        words = []
        try:
            with open(self.seed_csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    word = row.get("word")
                    if word:
                        words.append(word.strip().lower())
            words = sorted(list(set(words)))  # deduplicate and sort
        except Exception as e:
            raise RuntimeError(
                f"Failed to read seed CSV file from {self.seed_csv_path}: {e}"
            ) from e

        if not words:
            raise ValueError(f"No valid words found in {self.seed_csv_path}")

        # Lazy load model
        logger.info(f"Initializing SentenceTransformer model '{self.model_name}'...")
        self.model = self._transformer_class(self.model_name)

        logger.info(f"Encoding {len(words)} seed words (this may take a moment)...")
        embeddings = self.model.encode(words, show_progress_bar=False)

        # Cache results
        try:
            self.cache_npz_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                self.cache_npz_path,
                words=words,
                embeddings=embeddings,
            )
            logger.info(
                f"Successfully saved compiled embeddings to {self.cache_npz_path}"
            )
        except Exception as e:
            logger.warning(
                f"Could not save embedding cache to {self.cache_npz_path}: {e}"
            )

        self.seed_words = words
        self.seed_embeddings = embeddings
        norms = np.linalg.norm(self.seed_embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.normalized_seeds = self.seed_embeddings / norms

    def _lazy_load_model(self) -> Any:
        """Loads the transformer model if it hasn't been loaded yet."""
        if self.model is None:
            logger.info(f"Loading SentenceTransformer model '{self.model_name}'...")
            self.model = self._transformer_class(self.model_name)
        return self.model

    def score(self, word: str) -> float:
        """
        Scores a candidate word using the mean cosine similarity of its
        K-Nearest Neighbors in the seed set.
        """
        if not self.seed_words:
            return 0.0

        np = self._np
        model = self._lazy_load_model()

        # Embed candidate word
        try:
            candidate_vector = model.encode([word], show_progress_bar=False)[0]
        except Exception as e:
            logger.error(f"Failed to encode word '{word}': {e}")
            return 0.0

        # Compute L2 norm of candidate vector
        cand_norm_val = np.linalg.norm(candidate_vector)
        if cand_norm_val == 0:
            return 0.0
        cand_norm = candidate_vector / cand_norm_val

        # Vectorized cosine similarities via dot product
        similarities = np.dot(self.normalized_seeds, cand_norm)

        # Get top-k similarities
        k = min(self.k, len(similarities))
        if k <= 0:
            return 0.0

        # Partition similarity array to get top-k largest elements in O(N)
        top_k_sims = np.partition(similarities, -k)[-k:]

        # Return mean similarity
        return float(np.mean(top_k_sims))


class CompositeScorer:
    """
    Combines multiple scorers using weighted linear combination.
    """

    def __init__(self, scorers_with_weights: list[tuple[WordScorer, float]]) -> None:
        self.scorers_with_weights = scorers_with_weights

    @property
    def higher_is_better(self) -> bool:
        # A weighted score combination generally means higher is better
        return True

    def score(self, word: str) -> float:
        """
        Returns the weighted sum of scores from all sub-scorers.
        """
        total_score = 0.0
        for scorer, weight in self.scorers_with_weights:
            total_score += weight * scorer.score(word)
        return total_score
