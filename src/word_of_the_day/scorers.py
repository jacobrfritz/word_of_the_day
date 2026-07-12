import csv
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from wordfreq import zipf_frequency

from .logger import get_logger

if TYPE_CHECKING:
    import numpy as np
    from sentence_transformers import SentenceTransformer

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
        except ImportError as e:
            raise ImportError(
                "EmbeddingScorer requires 'sentence-transformers' "
                "and 'numpy' packages. Please install them using: "
                "uv pip install sentence-transformers numpy"
            ) from e

        self.seed_words: list[str] = []
        self.seed_embeddings: np.ndarray = np.empty((0, 0))
        self.normalized_seeds: np.ndarray = np.empty((0, 0))
        self.model: SentenceTransformer | None = None
        self.target_centroid: np.ndarray | None = None
        self.target_centroid_normalized: np.ndarray | None = None

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
        import numpy as np

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
        import numpy as np

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
        model = self._lazy_load_model()

        logger.info(f"Encoding {len(words)} seed words (this may take a moment)...")
        embeddings = model.encode(words, show_progress_bar=False)

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

    def _lazy_load_model(self) -> "SentenceTransformer":
        """Loads the transformer model if it hasn't been loaded yet."""
        if self.model is None:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading SentenceTransformer model '{self.model_name}'...")
            self.model = SentenceTransformer(self.model_name)
        return self.model

    def score(self, word: str) -> float:
        """
        Scores a candidate word. If target_centroid is set, scores using cosine
        similarity to the target centroid. Otherwise, uses the mean cosine
        similarity of its K-Nearest Neighbors in the seed set.
        """
        if not self.seed_words:
            return 0.0

        import numpy as np

        model = self._lazy_load_model()

        # Embed candidate word
        try:
            candidate_vector = cast(
                "np.ndarray",
                model.encode([word], show_progress_bar=False)[0],
            )
        except Exception as e:
            logger.error(f"Failed to encode word '{word}': {e}")
            return 0.0

        # Compute L2 norm of candidate vector
        cand_norm_val = np.linalg.norm(candidate_vector)
        if cand_norm_val == 0:
            return 0.0
        cand_norm = candidate_vector / cand_norm_val

        # If target centroid is set, compute cosine similarity directly to it
        if self.target_centroid_normalized is not None:
            similarity = np.dot(self.target_centroid_normalized, cand_norm)
            return float(similarity)

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

    def set_target_centroid(self, centroid: "np.ndarray | None") -> None:
        """
        Sets the active target centroid for scoring candidates.
        """
        import numpy as np
        self.target_centroid = centroid
        if centroid is not None:
            norm = np.linalg.norm(centroid)
            self.target_centroid_normalized = centroid / (norm if norm > 0 else 1.0)
        else:
            self.target_centroid_normalized = None

    def get_optimal_seed_clusters(self, k_min: int = 2, k_max: int = 10) -> tuple["np.ndarray", int]:
        """
        Finds the optimal number of clusters using the Elbow Method (diminishing returns)
        and returns the sorted centroids.
        """
        try:
            from sklearn.cluster import KMeans
            import numpy as np
        except ImportError as e:
            raise ImportError(
                "Clustering requires 'scikit-learn' and 'numpy'. "
                "Please install them using: uv pip install scikit-learn numpy"
            ) from e

        seed_embeddings = self.seed_embeddings
        if len(seed_embeddings) == 0 or seed_embeddings.shape[0] == 0:
            raise ValueError("No seed embeddings available for clustering.")

        inertias = []
        # Ensure we don't try to find more clusters than we have seed words
        max_possible_k = min(k_max, len(seed_embeddings) - 1)
        K_range = range(k_min, max_possible_k + 1)

        # Handle case where K_range is empty (very few seed words)
        if not K_range:
            optimal_k = max(1, len(seed_embeddings))
            kmeans = KMeans(n_clusters=optimal_k, random_state=42, n_init="auto")
            kmeans.fit(seed_embeddings)
            centroids = kmeans.cluster_centers_
            sorted_indices = np.argsort(np.linalg.norm(centroids, axis=1))
            return centroids[sorted_indices], optimal_k

        # 1. Calculate inertia for each K
        for k in K_range:
            kmeans = KMeans(n_clusters=k, random_state=42, n_init="auto")
            kmeans.fit(seed_embeddings)
            inertias.append(kmeans.inertia_)

        # 2. Automate finding the "Elbow" (max distance from the line connecting endpoints)
        x1, y1 = K_range[0], inertias[0]
        x2, y2 = K_range[-1], inertias[-1]

        distances = []
        for i, k in enumerate(K_range):
            x3, y3 = k, inertias[i]
            # Orthogonal distance from point (x3, y3) to line connecting (x1, y1) and (x2, y2)
            numerator = np.abs((y2 - y1) * x3 - (x2 - x1) * y3 + x2 * y1 - x1 * y2)
            denominator = np.sqrt((y2 - y1) ** 2 + (x2 - x1) ** 2)
            dist = numerator / denominator if denominator > 0 else 0.0
            distances.append(dist)

        optimal_k = K_range[np.argmax(distances)]

        # 3. Perform final clustering with optimal K
        final_kmeans = KMeans(n_clusters=optimal_k, random_state=42, n_init="auto")
        final_kmeans.fit(seed_embeddings)
        centroids = final_kmeans.cluster_centers_

        # 4. Sort centroids deterministically by vector norm
        sorted_indices = np.argsort(np.linalg.norm(centroids, axis=1))
        stable_centroids = centroids[sorted_indices]

        return stable_centroids, optimal_k


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
