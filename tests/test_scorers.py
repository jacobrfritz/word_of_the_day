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
