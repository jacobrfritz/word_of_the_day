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

    def score_batch(self, words: list[str]) -> list[float]:
        """
        Score a list of words. Higher scores indicate more suitable candidates.

        Args:
            words: The list of words to score.

        Returns:
            A list of float scores corresponding to the input words.
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

    def score_batch(self, words: list[str]) -> list[float]:
        """
        Returns the Zipf frequency scores of the words.
        """
        return [zipf_frequency(word, self.lang) for word in words]


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
        self.active_cluster_id: int | None = None
        self.cluster_labels: np.ndarray | None = None
        self.cluster_optimal_k: int = 0

        self._initialize()

    @property
    def higher_is_better(self) -> bool:
        # Cosine similarity: closer to seed words (higher similarity) is better
        return True

    def _initialize(self) -> None:
        """Loads or precomputes the seed word embeddings."""
        cache_exists = self.cache_npz_path.exists()
        csv_exists = self.seed_csv_path.exists()

        if not cache_exists and not csv_exists:
            try:
                self._bootstrap_seed_csv()
                csv_exists = True
            except Exception as e:
                raise FileNotFoundError(
                    f"Neither the embedding cache ({self.cache_npz_path}) nor "
                    f"the seed CSV file ({self.seed_csv_path}) was found, and auto-bootstrap failed: {e}"
                ) from e

        # If both cache and CSV exist, check if cache is consistent with the CSV
        should_recompile = not cache_exists
        if cache_exists and csv_exists:
            try:
                import numpy as np

                cache_data = np.load(self.cache_npz_path, allow_pickle=True)
                cached_words = set(cache_data["words"])

                csv_words = set()
                with open(self.seed_csv_path, encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        word = row.get("word")
                        if word:
                            csv_words.add(word.strip().lower())

                if csv_words != cached_words:
                    logger.info(
                        "Seed CSV words differ from cached embeddings. Triggering recompilation..."
                    )
                    should_recompile = True
            except Exception as e:
                logger.warning(f"Error checking cache consistency: {e}. Recompiling...")
                should_recompile = True

        if should_recompile:
            self._compile_cache()
        else:
            self._load_cache()

    def _bootstrap_seed_csv(self) -> None:
        """
        Automatically fetches the Word of the Day RSS feed and compiles the
        seed CSV file if it's missing on the first run.
        """
        import email.utils

        import requests
        from bs4 import BeautifulSoup

        logger.info("Auto-bootstrapping seed CSV file from RSS feed...")
        headers = {"User-Agent": "Mozilla/5.0"}
        podcast_feed_url = "https://rss.art19.com/merriam-websters-word-of-the-day"

        try:
            r = requests.get(podcast_feed_url, headers=headers, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "xml")
            items = soup.find_all("item")

            records: list[dict[str, str]] = []
            for item in items:
                title_el = item.find("title")
                pub_date_el = item.find("pubDate")
                if title_el and pub_date_el:
                    word = title_el.text.strip().lower()
                    pub_date_str = pub_date_el.text.strip()
                    try:
                        dt = email.utils.parsedate_to_datetime(pub_date_str)
                        date_str = dt.strftime("%Y-%m-%d")
                    except Exception:
                        continue
                    if word and date_str:
                        records.append({"word": word, "date": date_str})

            # Sort records by date ascending
            records.sort(key=lambda x: x["date"])

            # If RSS failed to return items, use fallbacks
            if not records:
                raise ValueError("No records found in RSS feed.")

        except Exception as e:
            logger.warning(f"Failed to fetch RSS feed: {e}. Using fallback seed words.")
            # Hardcoded fallbacks to guarantee bootstrap even offline
            fallbacks = [
                ("2026-07-01", "sagacious"),
                ("2026-07-02", "loquacious"),
                ("2026-07-03", "capricious"),
                ("2026-07-04", "ephemeral"),
                ("2026-07-05", "taciturn"),
                ("2026-07-06", "gregarious"),
                ("2026-07-07", "alacrity"),
                ("2026-07-08", "cacophony"),
                ("2026-07-09", "mercurial"),
                ("2026-07-10", "pernicious"),
            ]
            records = [{"word": w, "date": d} for d, w in fallbacks]

        # Ensure parent directories exist
        self.seed_csv_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to CSV
        with open(self.seed_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["word", "date"])
            writer.writeheader()
            writer.writerows(records)

        logger.info(
            f"Successfully bootstrapped {len(records)} seed words to {self.seed_csv_path}"
        )

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

        # Filter seeds by active cluster if set
        if self.active_cluster_id is not None and self.cluster_labels is not None:
            cluster_mask = (self.cluster_labels == self.active_cluster_id)
            if np.any(cluster_mask):
                normalized_seeds_to_use = self.normalized_seeds[cluster_mask]
            else:
                normalized_seeds_to_use = self.normalized_seeds
        else:
            normalized_seeds_to_use = self.normalized_seeds

        # Vectorized cosine similarities via dot product
        similarities = np.dot(normalized_seeds_to_use, cand_norm)

        # Get top-k similarities
        k = min(self.k, len(similarities))
        if k <= 0:
            return 0.0

        # Partition similarity array to get top-k largest elements in O(N)
        top_k_sims = np.partition(similarities, -k)[-k:]

        # Return mean similarity
        return float(np.mean(top_k_sims))

    def score_batch(self, words: list[str]) -> list[float]:
        """
        Scores a list of candidate words in a batch.
        """
        if not self.seed_words or not words:
            return [0.0] * len(words)

        import numpy as np

        model = self._lazy_load_model()

        # Embed candidate words in a single batch pass
        try:
            candidate_vectors = cast(
                "np.ndarray",
                model.encode(words, show_progress_bar=False),
            )
        except Exception as e:
            logger.error(f"Failed to encode batch of words: {e}")
            return [0.0] * len(words)

        # Compute L2 norms of candidate vectors
        # If candidate_vectors is 1D (because only 1 word was encoded, model.encode might still return 2D array of shape (1, dim))
        # model.encode(list[str]) always returns a 2D array of shape (num_words, embedding_dim).
        cand_norms = np.linalg.norm(candidate_vectors, axis=1, keepdims=True)
        cand_norms[cand_norms == 0] = 1.0
        normalized_candidates = candidate_vectors / cand_norms

        if self.target_centroid_normalized is not None:
            # Cosine similarity is the dot product of normalized vectors
            # target_centroid_normalized shape: (embedding_dim,)
            # normalized_candidates shape: (num_words, embedding_dim)
            similarities = np.dot(
                normalized_candidates, self.target_centroid_normalized
            )
            return [float(s) for s in similarities]

        # Filter seeds by active cluster if set
        if self.active_cluster_id is not None and self.cluster_labels is not None:
            cluster_mask = (self.cluster_labels == self.active_cluster_id)
            if np.any(cluster_mask):
                normalized_seeds_to_use = self.normalized_seeds[cluster_mask]
            else:
                normalized_seeds_to_use = self.normalized_seeds
        else:
            normalized_seeds_to_use = self.normalized_seeds

        # Vectorized cosine similarities via dot product
        # normalized_seeds_to_use shape: (num_seeds, embedding_dim)
        # normalized_candidates.T shape: (embedding_dim, num_words)
        # similarities shape: (num_seeds, num_words)
        similarities = np.dot(normalized_seeds_to_use, normalized_candidates.T)

        k = min(self.k, len(normalized_seeds_to_use))
        if k <= 0:
            return [0.0] * len(words)

        # For each candidate, we need the mean of the top-k similarities.
        # np.partition partitions along axis 0 (the seed dimension) for each column.
        top_k_sims = np.partition(similarities, -k, axis=0)[-k:, :]
        mean_sims = np.mean(top_k_sims, axis=0)
        return [float(s) for s in mean_sims]

    def get_similar_words(
        self, target_word: str, k: int = 3
    ) -> list[tuple[str, float]]:
        """
        Computes the dot product of the target_word's vector against all
        normalized_seeds. Returns the top `k` most similar words, excluding
        the target word itself.
        """
        if not self.seed_words or len(self.normalized_seeds) == 0:
            return []

        import numpy as np

        model = self._lazy_load_model()

        try:
            target_vector = cast(
                "np.ndarray",
                model.encode([target_word], show_progress_bar=False)[0],
            )
        except Exception as e:
            logger.error(f"Failed to encode target word '{target_word}': {e}")
            return []

        norm_val = np.linalg.norm(target_vector)
        if norm_val == 0:
            return []
        target_norm = target_vector / norm_val

        similarities = np.dot(self.normalized_seeds, target_norm)
        sorted_indices = np.argsort(-similarities)

        results: list[tuple[str, float]] = []
        cleaned_target = target_word.strip().lower()
        for idx in sorted_indices:
            seed_word = self.seed_words[idx]
            if seed_word.strip().lower() != cleaned_target:
                results.append((seed_word, float(similarities[idx])))
                if len(results) == k:
                    break

        return results


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

    def set_active_cluster(self, cluster_id: int | None, optimal_k: int) -> None:
        """
        Sets the active cluster ID for scoring candidates using KNN within the cluster.
        If cluster_id is None, clears the active cluster filter (scores against all seeds).
        """
        import numpy as np

        self.active_cluster_id = cluster_id
        if cluster_id is None or optimal_k <= 0:
            self.cluster_labels = None
            self.cluster_optimal_k = 0
            return

        # Perform clustering to assign seeds to clusters (deterministic via random_state=42)
        try:
            from sklearn.cluster import KMeans
        except ImportError as e:
            raise ImportError(
                "Clustering requires 'scikit-learn'. Please install it using: uv pip install scikit-learn"
            ) from e

        seed_embeddings = self.seed_embeddings
        if len(seed_embeddings) == 0:
            raise ValueError("No seed embeddings available for clustering.")

        # Ensure optimal_k is valid
        optimal_k = min(optimal_k, len(seed_embeddings))

        # Fit K-Means
        kmeans = KMeans(n_clusters=optimal_k, random_state=42, n_init="auto")
        labels = kmeans.fit_predict(seed_embeddings)
        centroids = kmeans.cluster_centers_

        # Sort centroids deterministically by vector norm
        sorted_indices = np.argsort(np.linalg.norm(centroids, axis=1))
        # Map original labels to the new sorted order labels
        label_mapping = {old: new for new, old in enumerate(sorted_indices)}
        sorted_labels = np.array([label_mapping[l] for l in labels])

        self.cluster_labels = sorted_labels
        self.cluster_optimal_k = optimal_k

    def get_optimal_seed_clusters(
        self, k_min: int = 2, k_max: int = 10
    ) -> tuple["np.ndarray", int]:
        """
        Finds the optimal number of clusters using the Elbow Method (diminishing returns)
        and returns the sorted centroids.
        """
        try:
            import numpy as np
            from sklearn.cluster import KMeans  # type: ignore[import-untyped]
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
        k_range = range(k_min, max_possible_k + 1)

        # Handle case where k_range is empty (very few seed words)
        if not k_range:
            optimal_k = max(1, len(seed_embeddings))
            kmeans = KMeans(n_clusters=optimal_k, random_state=42, n_init="auto")
            kmeans.fit(seed_embeddings)
            centroids = kmeans.cluster_centers_
            sorted_indices = np.argsort(np.linalg.norm(centroids, axis=1))
            return centroids[sorted_indices], optimal_k

        # 1. Calculate inertia for each K
        for k in k_range:
            kmeans = KMeans(n_clusters=k, random_state=42, n_init="auto")
            kmeans.fit(seed_embeddings)
            inertias.append(kmeans.inertia_)

        # 2. Automate finding the "Elbow" (max distance from the line connecting endpoints)
        x1, y1 = k_range[0], inertias[0]
        x2, y2 = k_range[-1], inertias[-1]

        distances = []
        for i, k in enumerate(k_range):
            x3, y3 = k, inertias[i]
            # Orthogonal distance from point (x3, y3) to line connecting (x1, y1) and (x2, y2)
            numerator = np.abs((y2 - y1) * x3 - (x2 - x1) * y3 + x2 * y1 - x1 * y2)
            denominator = np.sqrt((y2 - y1) ** 2 + (x2 - x1) ** 2)
            dist = numerator / denominator if denominator > 0 else 0.0
            distances.append(dist)

        optimal_k = k_range[np.argmax(distances)]

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

    def score_batch(self, words: list[str]) -> list[float]:
        """
        Returns the weighted sum of scores from all sub-scorers in a batch.
        """
        if not words:
            return []

        # Initialize total scores to 0.0
        total_scores = [0.0] * len(words)
        for scorer, weight in self.scorers_with_weights:
            if hasattr(scorer, "score_batch"):
                scores = scorer.score_batch(words)
            else:
                scores = [scorer.score(word) for word in words]
            for i, score in enumerate(scores):
                total_scores[i] += weight * score
        return total_scores


class TFIDFScorer:
    """
    Scores words based on TF-IDF computed over a corpus of documents.
    """

    def __init__(
        self, stop_words: str | list[str] | set[str] | None = "english"
    ) -> None:
        self.stop_words = stop_words

    @property
    def higher_is_better(self) -> bool:
        return True

    def score(self, word: str) -> float:
        """
        No-op fallback for WordScorer interface compatibility.
        """
        return 0.0

    def score_batch(self, words: list[str]) -> list[float]:
        """
        No-op fallback for WordScorer interface compatibility.
        """
        return [0.0] * len(words)

    def get_top_words(self, documents: list[str], limit: int = 500) -> list[str]:
        """
        Fits on the documents, calculates the maximum TF-IDF score for each word
        across all documents, and returns the top `limit` unique words.
        """
        if not documents or not any(doc.strip() for doc in documents):
            return []

        try:
            import numpy as np
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError as e:
            raise ImportError(
                "TFIDFScorer requires 'scikit-learn' and 'numpy' packages. "
                "Please install them using: uv pip install scikit-learn numpy"
            ) from e

        # Ensure stop words parameter is list if it is a set
        stop_words_param = self.stop_words
        if isinstance(stop_words_param, set):
            stop_words_param = list(stop_words_param)

        try:
            vectorizer = TfidfVectorizer(stop_words=stop_words_param)
            tfidf_matrix = vectorizer.fit_transform(documents)
            feature_names = vectorizer.get_feature_names_out()
        except ValueError:
            # Handle case where all documents contain only stop words
            return []

        if tfidf_matrix.shape[0] == 0 or tfidf_matrix.shape[1] == 0:
            return []

        # Get max TF-IDF score for each word across all documents
        max_tfidf = np.array(tfidf_matrix.max(axis=0).todense()).flatten()

        # Sort the features based on max TF-IDF score descending
        top_indices = np.argsort(max_tfidf)[::-1][:limit]

        return [str(feature_names[i]) for i in top_indices]

    def get_top_words_with_scores(
        self, documents: list[str], limit: int = 500
    ) -> list[tuple[str, float]]:
        """
        Fits on the documents, calculates the maximum TF-IDF score for each word
        across all documents, and returns the top `limit` unique words with their scores.
        """
        if not documents or not any(doc.strip() for doc in documents):
            return []

        try:
            import numpy as np
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError as e:
            raise ImportError(
                "TFIDFScorer requires 'scikit-learn' and 'numpy' packages. "
                "Please install them using: uv pip install scikit-learn numpy"
            ) from e

        # Ensure stop words parameter is list if it is a set
        stop_words_param = self.stop_words
        if isinstance(stop_words_param, set):
            stop_words_param = list(stop_words_param)

        try:
            vectorizer = TfidfVectorizer(stop_words=stop_words_param)
            tfidf_matrix = vectorizer.fit_transform(documents)
            feature_names = vectorizer.get_feature_names_out()
        except ValueError:
            # Handle case where all documents contain only stop words
            return []

        if tfidf_matrix.shape[0] == 0 or tfidf_matrix.shape[1] == 0:
            return []

        # Get max TF-IDF score for each word across all documents
        max_tfidf = np.array(tfidf_matrix.max(axis=0).todense()).flatten()

        # Sort the features based on max TF-IDF score descending
        top_indices = np.argsort(max_tfidf)[::-1][:limit]

        return [(str(feature_names[i]), float(max_tfidf[i])) for i in top_indices]
