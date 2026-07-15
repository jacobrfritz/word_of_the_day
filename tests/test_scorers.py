import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from word_of_the_day.scorers import (
    CompositeScorer,
    EmbeddingScorer,
    ZipfScorer,
)


def test_zipf_scorer() -> None:
    """Verifies that ZipfScorer calculates Zipf scores correctly."""
    scorer = ZipfScorer()
    assert not scorer.higher_is_better

    # "the" is common, "serendipity" is rare
    score_the = scorer.score("the")
    score_serendipity = scorer.score("serendipity")

    assert score_the > 4.0
    assert score_serendipity < 4.0
    assert score_the > score_serendipity


@patch("sentence_transformers.SentenceTransformer")
def test_embedding_scorer_lazy_compilation(
    mock_transformer_class: MagicMock, tmp_path: Path
) -> None:
    """Verifies that EmbeddingScorer compiles the cache if it doesn't exist."""
    csv_path = tmp_path / "seeds.csv"
    cache_path = tmp_path / "cache.npz"

    # Write dummy CSV
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["word", "date"])
        writer.writerow(["serendipity", "2026-07-09"])
        writer.writerow(["solitude", "2026-07-08"])

    # Mock the transformer model instance
    mock_model = MagicMock()
    mock_transformer_class.return_value = mock_model

    # Return dummy embeddings of size 384
    import numpy as np

    mock_model.encode.return_value = np.random.rand(2, 384)

    # Initialize scorer (triggers compilation because cache_path does not exist)
    scorer = EmbeddingScorer(
        seed_csv_path=csv_path,
        cache_npz_path=cache_path,
        model_name="dummy-model",
        k=1,
    )

    assert scorer.higher_is_better
    assert len(scorer.seed_words) == 2
    assert "serendipity" in scorer.seed_words
    assert "solitude" in scorer.seed_words
    assert cache_path.exists()

    # Verify model encode was called
    mock_transformer_class.assert_called_once_with("dummy-model")
    mock_model.encode.assert_called_once()


@patch("sentence_transformers.SentenceTransformer")
def test_embedding_scorer_loading_from_cache(
    mock_transformer_class: MagicMock, tmp_path: Path
) -> None:
    """Verifies that EmbeddingScorer loads from cache if it exists, without encoding."""
    csv_path = tmp_path / "seeds.csv"
    cache_path = tmp_path / "cache.npz"

    import numpy as np

    # Pre-save compiled embeddings cache
    words = np.array(["serendipity", "solitude"])
    # 2 words, 384 dims
    embeddings = np.random.rand(2, 384)
    np.savez_compressed(cache_path, words=words, embeddings=embeddings)

    # Mock the model
    mock_model = MagicMock()
    mock_transformer_class.return_value = mock_model

    scorer = EmbeddingScorer(
        seed_csv_path=csv_path,
        cache_npz_path=cache_path,
        model_name="dummy-model",
        k=1,
    )

    assert len(scorer.seed_words) == 2
    assert scorer.seed_words == ["serendipity", "solitude"]
    # Model should not have been loaded/initialized during init because cache exists
    mock_transformer_class.assert_not_called()


@patch("sentence_transformers.SentenceTransformer")
def test_embedding_scorer_calculation(
    mock_transformer_class: MagicMock, tmp_path: Path
) -> None:
    """Verifies K-Nearest Neighbors calculation."""
    csv_path = tmp_path / "seeds.csv"
    cache_path = tmp_path / "cache.npz"

    import numpy as np

    # Seed words: 3 distinct vectors in 2D space
    # (using small dimensions for simplicity)
    words = np.array(["a", "b", "c"])
    embeddings = np.array(
        [
            [1.0, 0.0],  # "a"
            [0.0, 1.0],  # "b"
            [0.707, 0.707],  # "c" (diagonal)
        ],
        dtype=np.float32,
    )
    np.savez_compressed(cache_path, words=words, embeddings=embeddings)

    mock_model = MagicMock()
    mock_transformer_class.return_value = mock_model

    # Candidate "test" embeds as [1.0, 0.0]
    # Cosine similarities:
    # to "a" -> 1.0
    # to "b" -> 0.0
    # to "c" -> 0.707
    mock_model.encode.return_value = np.array([[1.0, 0.0]], dtype=np.float32)

    scorer = EmbeddingScorer(
        seed_csv_path=csv_path,
        cache_npz_path=cache_path,
        model_name="dummy-model",
        k=2,
    )

    # Score "test"
    score = scorer.score("test")

    # Top k=2 similarities are 1.0 and 0.707
    # Mean of top 2 = (1.0 + 0.707) / 2 = 0.8535
    assert pytest.approx(score, 0.001) == 0.8535


def test_composite_scorer() -> None:
    """Verifies that CompositeScorer combines sub-scorers properly."""
    mock_scorer1 = MagicMock()
    mock_scorer1.score.return_value = 0.5
    mock_scorer2 = MagicMock()
    mock_scorer2.score.return_value = 0.8

    # Weights: 0.6 for scorer1, 0.4 for scorer2
    # Combined score = 0.6 * 0.5 + 0.4 * 0.8 = 0.3 + 0.32 = 0.62
    composite = CompositeScorer(
        [
            (mock_scorer1, 0.6),
            (mock_scorer2, 0.4),
        ]
    )

    assert composite.higher_is_better
    assert pytest.approx(composite.score("word")) == 0.62
    mock_scorer1.score.assert_called_once_with("word")
    mock_scorer2.score.assert_called_once_with("word")


def test_embedding_scorer_missing_dependencies() -> None:
    """Verifies that missing dependencies raise an ImportError."""
    with patch.dict(sys.modules, {"sentence_transformers": None}):
        with pytest.raises(ImportError) as exc_info:
            EmbeddingScorer(seed_csv_path="dummy.csv", cache_npz_path="dummy.npz")
        assert "EmbeddingScorer requires" in str(exc_info.value)


@patch("sentence_transformers.SentenceTransformer")
def test_embedding_scorer_clustering_and_target_scoring(
    mock_transformer_class: MagicMock, tmp_path: Path
) -> None:
    """Verifies that EmbeddingScorer correctly clusters seed words and scores candidates using target centroid."""
    csv_path = tmp_path / "seeds.csv"
    cache_path = tmp_path / "cache.npz"

    import numpy as np

    # Pre-save compiled embeddings: 5 words in 2D space
    words = np.array(["apple", "apricot", "banana", "blueberry", "cherry"])
    embeddings = np.array(
        [
            [1.0, 0.1],  # Group A (apple)
            [0.9, 0.2],  # Group A (apricot)
            [0.1, 1.0],  # Group B (banana)
            [0.2, 0.9],  # Group B (blueberry)
            [0.5, 0.5],  # Group C (cherry)
        ],
        dtype=np.float32,
    )
    np.savez_compressed(cache_path, words=words, embeddings=embeddings)

    mock_model = MagicMock()
    mock_transformer_class.return_value = mock_model

    # Initialize scorer
    scorer = EmbeddingScorer(
        seed_csv_path=csv_path,
        cache_npz_path=cache_path,
        model_name="dummy-model",
    )

    # 1. Test get_optimal_seed_clusters
    stable_centroids, optimal_k = scorer.get_optimal_seed_clusters(k_min=2, k_max=3)
    assert optimal_k in (2, 3)
    assert stable_centroids.shape == (optimal_k, 2)

    # Centroids should be sorted by norm
    norms = np.linalg.norm(stable_centroids, axis=1)
    assert np.all(np.diff(norms) >= 0)

    # 2. Test set_target_centroid & scoring directly against the centroid
    target_centroid = np.array([1.0, 0.0], dtype=np.float32)
    scorer.set_target_centroid(target_centroid)

    # Candidate "test" embeds as [1.0, 0.0] -> similarity should be 1.0
    mock_model.encode.return_value = np.array([[1.0, 0.0]], dtype=np.float32)
    score_perfect = scorer.score("test")
    assert pytest.approx(score_perfect, 0.001) == 1.0

    # Candidate "test2" embeds as [0.0, 1.0] -> similarity should be 0.0
    mock_model.encode.return_value = np.array([[0.0, 1.0]], dtype=np.float32)
    score_orthogonal = scorer.score("test2")
    assert pytest.approx(score_orthogonal, 0.001) == 0.0

    # Revert target centroid
    scorer.set_target_centroid(None)
    assert scorer.target_centroid_normalized is None


@patch("sentence_transformers.SentenceTransformer")
def test_embedding_scorer_auto_recompile(
    mock_transformer_class: MagicMock, tmp_path: Path
) -> None:
    """Verifies that EmbeddingScorer auto-recompiles cache when CSV words differ from NPZ cache."""
    csv_path = tmp_path / "seeds.csv"
    cache_path = tmp_path / "cache.npz"

    import numpy as np

    # 1. Pre-save cache with 2 words
    words = np.array(["serendipity", "solitude"])
    embeddings = np.random.rand(2, 384)
    np.savez_compressed(cache_path, words=words, embeddings=embeddings)

    # 2. Write CSV with the same 2 words (aligned)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["word", "date"])
        writer.writerow(["serendipity", "2026-07-09"])
        writer.writerow(["solitude", "2026-07-08"])

    # Mock the transformer
    mock_model = MagicMock()
    mock_transformer_class.return_value = mock_model
    mock_model.encode.return_value = np.random.rand(3, 384)

    # First init: cache matches CSV, no compilation should happen
    scorer1 = EmbeddingScorer(
        seed_csv_path=csv_path,
        cache_npz_path=cache_path,
        model_name="dummy-model",
        k=1,
    )
    assert len(scorer1.seed_words) == 2
    mock_transformer_class.assert_not_called()

    # 3. Modify CSV by adding a new word "antigravity" (mismatched)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["antigravity", "2026-07-10"])

    # Second init: cache does NOT match CSV, should trigger recompilation
    scorer2 = EmbeddingScorer(
        seed_csv_path=csv_path,
        cache_npz_path=cache_path,
        model_name="dummy-model",
        k=1,
    )
    assert len(scorer2.seed_words) == 3
    assert "antigravity" in scorer2.seed_words
    mock_transformer_class.assert_called_once_with("dummy-model")
    mock_model.encode.assert_called_once()


