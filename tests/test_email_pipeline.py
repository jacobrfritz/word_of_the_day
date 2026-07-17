# tests/test_email_pipeline.py
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from word_of_the_day.api import app
from word_of_the_day.config import settings
from word_of_the_day.email_sender import (
    parse_definition_and_pos,
    render_word_email,
    send_email_batch,
)
from word_of_the_day.storage import Storage


@pytest.fixture
def temp_storage() -> Generator[Storage, None, None]:
    # Use a temp database file for testing
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


def test_parse_definition_and_pos() -> None:
    # Format (partOfSpeech) Definition text
    definition_str = "(noun) A happy chance."
    def_text, pos = parse_definition_and_pos(definition_str)
    assert def_text == "A happy chance."
    assert pos == "noun"

    # Non-standard format
    definition_str2 = "A happy chance without POS."
    def_text2, pos2 = parse_definition_and_pos(definition_str2)
    assert def_text2 == "A happy chance without POS."
    assert pos2 == "unknown"

    # None definition
    def_text3, pos3 = parse_definition_and_pos(None)
    assert def_text3 == "No definition found."
    assert pos3 == "unknown"


def test_render_word_email() -> None:
    record = {
        "date": "2026-07-16",
        "word": "ephemeral",
        "definition": "(adjective) Lasting a short time.",
        "source": "Gutenberg",
        "score": 3.1234,
        "origin": "Greek ephemeros",
        "extra_info": None,
        "cluster_id": None,
    }
    unsubscribe_url = "http://localhost:8000/api/unsubscribe?token=testtoken123"
    html = render_word_email(record, unsubscribe_url)

    assert "EPHEMERAL" in html
    assert "adjective" in html
    assert "Lasting a short time." in html
    assert "Gutenberg" in html
    assert "3.1234" in html
    assert "Greek ephemeros" in html
    assert unsubscribe_url in html


def test_api_subscribe_validation_and_success(
    client: TestClient, temp_storage: Storage
) -> None:
    # 1. Invalid email check
    response = client.post("/api/subscribe", json={"email": "invalidemail"})
    assert response.status_code == 400
    assert "Invalid email format" in response.json()["detail"]

    # 2. Valid email check
    response2 = client.post("/api/subscribe", json={"email": "test@example.com"})
    assert response2.status_code == 200
    assert response2.json()["success"] is True

    # Check database record
    subscribers = temp_storage.get_active_subscribers()
    assert len(subscribers) == 1
    assert subscribers[0]["email"] == "test@example.com"
    assert len(subscribers[0]["unsubscribe_token"]) == 32  # UUID hex length

    # 3. Duplicate subscribe check (should fail when already active)
    response3 = client.post("/api/subscribe", json={"email": "test@example.com"})
    assert response3.status_code == 400
    assert "This email is already subscribed" in response3.json()["detail"]

    # 4. Reactivation check (unsubscribe first, then re-subscribe)
    token = subscribers[0]["unsubscribe_token"]
    temp_storage.unsubscribe(token)
    assert len(temp_storage.get_active_subscribers()) == 0

    response4 = client.post("/api/subscribe", json={"email": "test@example.com"})
    assert response4.status_code == 200
    assert response4.json()["success"] is True
    assert len(temp_storage.get_active_subscribers()) == 1


def test_api_unsubscribe_success_and_fail(
    client: TestClient, temp_storage: Storage
) -> None:
    # Subscribe a user first
    token = "test_uniq_unsubscribe_token_123"
    temp_storage.add_subscription("user@example.com", token)

    # Verify active
    subscribers = temp_storage.get_active_subscribers()
    assert len(subscribers) == 1
    assert subscribers[0]["email"] == "user@example.com"

    # Unsubscribe with invalid token
    response_fail = client.get("/api/unsubscribe?token=wrongtoken")
    assert response_fail.status_code == 200
    assert "Invalid Token" in response_fail.text

    # Unsubscribe with correct token
    response_success = client.get(f"/api/unsubscribe?token={token}")
    assert response_success.status_code == 200
    assert "Unsubscribed Successfully" in response_success.text

    # Verify inactive
    subscribers_after = temp_storage.get_active_subscribers()
    assert len(subscribers_after) == 0


def test_delivery_tracking_and_console_batch_dispatch(temp_storage: Storage) -> None:
    # Subscribe two users
    temp_storage.add_subscription("user1@example.com", "token1")
    temp_storage.add_subscription("user2@example.com", "token2")

    record = {
        "date": "2026-07-16",
        "word": "solitude",
        "definition": "(noun) State of being alone.",
        "source": "Wikipedia",
        "score": 3.8,
        "origin": "Latin solus",
        "extra_info": None,
        "cluster_id": None,
    }

    # Verify neither has received it yet
    assert not temp_storage.has_received_email("2026-07-16", "user1@example.com")
    assert not temp_storage.has_received_email("2026-07-16", "user2@example.com")

    # Set console backend config explicitly
    settings.smtp_backend = "console"

    subscribers = temp_storage.get_active_subscribers()
    sent_count = send_email_batch(subscribers, record, temp_storage)
    assert sent_count == 2

    # Verify they are logged as dispatched
    assert temp_storage.has_received_email("2026-07-16", "user1@example.com")
    assert temp_storage.has_received_email("2026-07-16", "user2@example.com")

    # Try sending again - should skip because of delivery tracking logs!
    sent_count_again = send_email_batch(subscribers, record, temp_storage)
    assert sent_count_again == 0
