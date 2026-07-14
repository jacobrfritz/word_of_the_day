import hashlib
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from word_of_the_day.api import app, get_storage
from word_of_the_day.config import settings
from word_of_the_day.main import run
from word_of_the_day.storage import Storage


@pytest.fixture
def temp_storage() -> Generator[Storage, None, None]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    storage = Storage(db_path=db_path, bootstrap=False)

    app.dependency_overrides[get_storage] = lambda: storage

    yield storage

    app.dependency_overrides.pop(get_storage, None)
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_admin_login_success(client: TestClient) -> None:
    # Use default password set in config setting
    password = settings.admin_password
    response = client.post("/api/admin/login", json={"password": password})
    assert response.status_code == 200
    token = response.json()["token"]
    assert token == hashlib.sha256(password.encode("utf-8")).hexdigest()


def test_admin_login_unauthorized(client: TestClient) -> None:
    response = client.post("/api/admin/login", json={"password": "wrongpassword"})
    assert response.status_code == 401


def test_admin_word_crud(client: TestClient, temp_storage: Storage) -> None:
    password = settings.admin_password
    token = hashlib.sha256(password.encode("utf-8")).hexdigest()
    headers = {"Authorization": f"Bearer {token}"}

    # Add a word
    payload = {
        "date": "2026-07-15",
        "word": "solitude",
        "definition": "state of being alone",
        "source": "Manual Selection",
        "origin": "Latin",
        "score": 4.2,
    }
    response = client.post("/api/admin/word", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify it exists in storage
    record = temp_storage.get_word_of_the_day("2026-07-15")
    assert record is not None
    assert record["word"] == "solitude"
    assert record["definition"] == "state of being alone"

    # Delete the word
    response = client.delete("/api/admin/word?date=2026-07-15", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify it is deleted
    assert temp_storage.get_word_of_the_day("2026-07-15") is None


def test_admin_word_auto_validation(client: TestClient, temp_storage: Storage) -> None:
    password = settings.admin_password
    token = hashlib.sha256(password.encode("utf-8")).hexdigest()
    headers = {"Authorization": f"Bearer {token}"}

    # Seed the cache so it doesn't query network
    temp_storage.cache_definition("serendipity", True, "happy chance", "English origin")

    payload = {"date": "2026-07-16", "word": "serendipity"}
    response = client.post("/api/admin/word", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    record = temp_storage.get_word_of_the_day("2026-07-16")
    assert record is not None
    assert record["word"] == "serendipity"
    assert record["definition"] == "happy chance"
    assert record["origin"] == "English origin"
    assert record["source"] == "Organic"


def test_admin_unauthorized_endpoints(client: TestClient) -> None:
    headers = {"Authorization": "Bearer badtoken"}

    # Try posting a word
    payload = {
        "date": "2026-07-15",
        "word": "solitude",
        "definition": "state of being alone",
        "source": "Manual Selection",
    }
    response = client.post("/api/admin/word", json=payload, headers=headers)
    assert response.status_code == 401

    # Try stats
    response = client.get("/api/admin/stats", headers=headers)
    assert response.status_code == 401


def test_admin_stats_and_clear_cache(client: TestClient, temp_storage: Storage) -> None:
    password = settings.admin_password
    token = hashlib.sha256(password.encode("utf-8")).hexdigest()
    headers = {"Authorization": f"Bearer {token}"}

    # Add dummy cache entry
    temp_storage.cache_definition("testword", True, "definition", "origin")

    # Get stats
    response = client.get("/api/admin/stats", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["cache_size"] == 1

    # Clear cache
    response = client.post("/api/admin/cache/clear", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Check stats again
    response = client.get("/api/admin/stats", headers=headers)
    data = response.json()
    assert data["cache_size"] == 0


def test_skip_auto_selection_if_exists(temp_storage: Storage) -> None:
    # Arrange: Save a pre-scheduled word in the db for 2026-07-20
    temp_storage.save_word_of_the_day(
        date="2026-07-20",
        word="prescheduled",
        definition="predefined definition",
        source="Manual Selection",
        score=3.0,
    )

    # Act: Run the selection CLI in 'auto' mode for that date
    # It should immediately skip and keep the pre-scheduled word
    run(mode="auto", date="2026-07-20", db_path=str(temp_storage.db_path))

    # Assert: Word is still 'prescheduled' and definition wasn't overwritten
    record = temp_storage.get_word_of_the_day("2026-07-20")
    assert record is not None
    assert record["word"] == "prescheduled"
    assert record["definition"] == "predefined definition"
