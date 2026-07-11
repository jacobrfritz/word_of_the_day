# tests/test_api.py
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import word_of_the_day.api
from word_of_the_day.api import app
from word_of_the_day.storage import Storage


@pytest.fixture
def temp_storage() -> Generator[Storage, None, None]:
    # Use a temp database file for testing the API routes
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    storage = Storage(db_path=db_path, bootstrap=False)

    # Store original and override in api module
    original_storage = word_of_the_day.api.storage
    word_of_the_day.api.storage = storage

    yield storage

    # Restore
    word_of_the_day.api.storage = original_storage
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_get_word_not_found(client: TestClient, temp_storage: Storage) -> None:
    # Query date that has no word
    response = client.get("/api/word?date=2026-07-10")
    assert response.status_code == 404
    assert "No Word of the Day has been selected" in response.json()["detail"]


def test_get_word_invalid_date(client: TestClient) -> None:
    response = client.get("/api/word?date=invalid-date")
    assert response.status_code == 400
    assert "Invalid date format" in response.json()["detail"]


def test_get_word_success(client: TestClient, temp_storage: Storage) -> None:
    # Save a word to the test storage
    temp_storage.save_word_of_the_day(
        date="2026-07-10",
        word="serendipity",
        definition="happy chance",
        source="wikipedia",
        score=3.5,
    )

    response = client.get("/api/word?date=2026-07-10")
    assert response.status_code == 200
    data = response.json()
    assert data["date"] == "2026-07-10"
    assert data["word"] == "serendipity"
    assert data["definition"] == "happy chance"
    assert data["source"] == "wikipedia"
    assert data["score"] == 3.5


def test_get_history(client: TestClient, temp_storage: Storage) -> None:
    # Add words to history
    temp_storage.save_word_of_the_day(
        date="2026-07-09", word="gambol", definition="skip", source="nyt", score=2.5
    )
    temp_storage.save_word_of_the_day(
        date="2026-07-10", word="tacit", definition="implied", source="wiki", score=2.8
    )

    response = client.get("/api/history")
    assert response.status_code == 200
    history = response.json()
    assert len(history) == 2
    # Ordered descending
    assert history[0]["date"] == "2026-07-10"
    assert history[1]["date"] == "2026-07-09"

    # Test limit query param
    response_limited = client.get("/api/history?limit=1")
    assert response_limited.status_code == 200
    assert len(response_limited.json()) == 1
    assert response_limited.json()[0]["date"] == "2026-07-10"


def test_serve_html_index(client: TestClient) -> None:
    # Verify GET / serves the HTML portal
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Word of the Day Portal" in response.text
