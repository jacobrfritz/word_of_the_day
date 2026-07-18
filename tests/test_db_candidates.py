# tests/test_db_candidates.py
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from word_of_the_day import main
from word_of_the_day.api import app, verify_admin
from word_of_the_day.storage import Storage


@pytest.fixture
def temp_db() -> Path:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)
    yield db_path
    import gc
    import sqlite3

    gc.collect()
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=DELETE;")
        conn.close()
    except Exception:
        pass
    for suffix in ["", "-wal", "-shm"]:
        p = Path(str(db_path) + suffix)
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


def test_storage_get_all_valid_cached_words(temp_db: Path) -> None:
    storage = Storage(db_path=temp_db, bootstrap=False)

    # Cache some valid and invalid words with/without source
    storage.cache_definition("ephemeral", True, "lasting a short time", "Greek", source="Wikipedia")
    storage.cache_definition("invalidword", False, "Not found", None, source="Poetry DB")
    storage.cache_definition("serendipity", True, "happy chance", "Persian")  # NULL source for backward compatibility

    valid_cached = storage.get_all_valid_cached_words()
    # Should only return valid words
    assert len(valid_cached) == 2
    words = {w["word"] for w in valid_cached}
    assert words == {"ephemeral", "serendipity"}

    # Verify keys and sources
    ephemeral_record = next(r for r in valid_cached if r["word"] == "ephemeral")
    assert ephemeral_record["definition"] == "lasting a short time"
    assert ephemeral_record["origin"] == "Greek"
    assert ephemeral_record["source"] == "Wikipedia"

    serendipity_record = next(r for r in valid_cached if r["word"] == "serendipity")
    assert serendipity_record["source"] is None


@patch("word_of_the_day.generator.WordSourceGenerator")
def test_run_pipeline_draws_from_database(
    mock_generator_class: MagicMock,
    temp_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Set up DB cache
    storage = Storage(db_path=temp_db, bootstrap=False)
    storage.cache_definition("serendipity", True, "happy chance", "Persian", source="Classic Poetry")

    # Mock generator to return no new text
    mock_generator = MagicMock()
    mock_generator.__enter__.return_value = mock_generator
    mock_generator.fetch_sources_by_connector.return_value = {}
    mock_generator.fetch_sources.return_value = ""
    mock_generator_class.return_value = mock_generator

    # Run the pipeline in list mode
    main.run(
        source="wikipedia",
        mode="list",
        db_path=str(temp_db),
        use_embeddings=False,
        use_lemmatization=False,
    )

    captured = capsys.readouterr()
    assert "Source: Classic Poetry" in captured.out
    assert "SERENDIPITY" in captured.out
    assert "happy chance" in captured.out


@patch("word_of_the_day.generator.WordSourceGenerator")
def test_api_explore_draws_from_database(
    mock_generator_class: MagicMock,
    temp_db: Path,
) -> None:
    # Set up DB cache
    storage = Storage(db_path=temp_db, bootstrap=False)
    storage.cache_definition("serendipity", True, "happy chance", "Persian", source="Classic Poetry")

    # Mock generator to return no new text
    mock_generator = MagicMock()
    mock_generator.__enter__.return_value = mock_generator
    mock_generator.fetch_sources_by_connector.return_value = {}
    mock_generator.fetch_sources.return_value = ""
    mock_generator_class.return_value = mock_generator

    # Override verify_admin dependency
    app.dependency_overrides[verify_admin] = lambda: True
    app.state.storage = storage

    client = TestClient(app)
    try:
        response = client.post(
            "/api/admin/explore",
            json={
                "sources": ["wikipedia"],
                "min_score": 2.3,
                "max_score": 4.0,
                "limit": 5,
                "use_embeddings": False,
                "use_lemmatization": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "candidates" in data
        candidates = data["candidates"]
        assert len(candidates) == 1
        assert candidates[0]["word"] == "serendipity"
        assert candidates[0]["source"] == "Classic Poetry"
        assert candidates[0]["definition"] == "happy chance"
        assert candidates[0]["origin"] == "Persian"
    finally:
        # Clean up dependency overrides
        app.dependency_overrides.clear()
