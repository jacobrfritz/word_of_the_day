# tests/test_api.py
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from word_of_the_day.api import app
from word_of_the_day.storage import Storage


@pytest.fixture
def temp_storage() -> Generator[Storage, None, None]:
    # Use a temp database file for testing the API routes
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    storage = Storage(db_path=db_path, bootstrap=False)

    # Register FastAPI dependency override
    from word_of_the_day.api import get_storage

    app.dependency_overrides[get_storage] = lambda: storage

    yield storage

    # Restore
    app.dependency_overrides.pop(get_storage, None)
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
        origin="test origin",
    )

    response = client.get("/api/word?date=2026-07-10")
    assert response.status_code == 200
    data = response.json()
    assert data["date"] == "2026-07-10"
    assert data["word"] == "serendipity"
    assert data["definition"] == "happy chance"
    assert data["source"] == "Encyclopedia"
    assert data["score"] == 3.5
    assert data["origin"] == "test origin"


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


def test_serve_static_files(client: TestClient) -> None:
    # Verify static files are mounted and served
    response_css = client.get("/static/style.css")
    assert response_css.status_code == 200
    assert "text/css" in response_css.headers["content-type"]
    assert "Design System & Variables" in response_css.text

    response_js = client.get("/static/index.js")
    assert response_js.status_code == 200
    assert "getLocalDateString" in response_js.text


def test_health_check(client: TestClient, temp_storage: Storage) -> None:
    # Verify health check endpoint succeeds
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


def test_security_headers(client: TestClient) -> None:
    # Verify security headers are present
    response = client.get("/")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("x-xss-protection") == "1; mode=block"
    assert "default-src 'self'" in response.headers.get("content-security-policy", "")
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_cors_headers(client: TestClient) -> None:
    # Verify CORS headers are present on API requests
    response = client.options(
        "/api/word",
        headers={
            "origin": "http://example.com",
            "access-control-request-method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://example.com"


def test_get_embeddings_grid(client: TestClient, temp_storage: Storage) -> None:
    # Initially history is empty, so endpoint should return empty list
    response_empty = client.get("/api/embeddings/grid")
    assert response_empty.status_code == 200
    assert response_empty.json() == []

    # Select seed words and save them to test history
    target_word = "sagacious"
    test_date = "2026-07-12"
    temp_storage.save_word_of_the_day(
        date=test_date,
        word=target_word,
        definition="test definition",
        source="wikipedia",
        score=3.0,
    )

    # Fetch again and confirm history mapping is merged in and filtered
    response_updated = client.get("/api/embeddings/grid")
    assert response_updated.status_code == 200
    data_updated = response_updated.json()
    assert len(data_updated) == 1

    point = data_updated[0]
    assert point["word"] == target_word
    assert "x" in point
    assert "y" in point
    assert "cluster_id" in point
    assert point["date"] == test_date
    assert point["source"] == "wikipedia"
    assert 0.0 <= point["x"] <= 1.0
    assert 0.0 <= point["y"] <= 1.0
    assert isinstance(point["cluster_id"], int)
