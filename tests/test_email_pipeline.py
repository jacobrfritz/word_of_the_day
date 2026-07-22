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
        "score": 0.1234,
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
    assert "0.1234" in html
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


def test_email_daily_cap_configuration() -> None:
    # Verify default config is 200
    assert settings.smtp_max_emails_per_day == 200


def test_storage_get_sent_count_for_day(temp_storage: Storage) -> None:
    # 1. Clean state should be 0
    assert temp_storage.get_sent_count_for_day("2026-07-17") == 0

    # 2. Insert dispatch logs manually with specific dates
    with temp_storage._connect() as conn:
        conn.execute(
            """
            INSERT INTO email_dispatch_log (date, email, sent_at)
            VALUES
                ('2026-07-17', 'user1@example.com', '2026-07-17T10:00:00.123456'),
                ('2026-07-17', 'user2@example.com', '2026-07-17T12:30:15.999999'),
                ('2026-07-18', 'user3@example.com', '2026-07-18T08:15:00.000000')
            """
        )
        conn.commit()

    # 3. Verify counts
    assert temp_storage.get_sent_count_for_day("2026-07-17") == 2
    assert temp_storage.get_sent_count_for_day("2026-07-18") == 1
    assert temp_storage.get_sent_count_for_day("2026-07-19") == 0


def test_email_batch_limit_capping(
    temp_storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    from word_of_the_day.email_sender import DailyEmailLimitExceededError

    # Configure max emails per day to 2
    monkeypatch.setattr(settings, "smtp_max_emails_per_day", 2)
    monkeypatch.setattr(settings, "smtp_backend", "console")

    # Subscribe three users
    temp_storage.add_subscription("user1@example.com", "token1")
    temp_storage.add_subscription("user2@example.com", "token2")
    temp_storage.add_subscription("user3@example.com", "token3")

    record = {
        "date": "2026-07-17",
        "word": "resilience",
        "definition": "(noun) Ability to recover.",
        "source": "Wikipedia",
        "score": 4.0,
        "origin": "Latin resilire",
        "extra_info": None,
        "cluster_id": None,
    }

    # Verify initial sent count for today is 0
    from datetime import datetime

    today_str = datetime.now().strftime("%Y-%m-%d")
    assert temp_storage.get_sent_count_for_day(today_str) == 0

    subscribers = temp_storage.get_active_subscribers()
    assert len(subscribers) == 3

    # Send batch - should raise DailyEmailLimitExceededError because smtp_max_emails_per_day is 2
    with pytest.raises(DailyEmailLimitExceededError):
        send_email_batch(subscribers, record, temp_storage)

    # Check today's sent count is exactly 2 (first 2 sent successfully)
    assert temp_storage.get_sent_count_for_day(today_str) == 2

    # The first two should have received it
    assert temp_storage.has_received_email("2026-07-17", "user1@example.com")
    assert temp_storage.has_received_email("2026-07-17", "user2@example.com")
    # The third should NOT have received it
    assert not temp_storage.has_received_email("2026-07-17", "user3@example.com")

    # If we try to send again (e.g. for the remaining subscribers), it should immediately raise the error because limit is reached
    with pytest.raises(DailyEmailLimitExceededError):
        send_email_batch(subscribers, record, temp_storage)


def test_email_batch_limit_capping_smtp(
    temp_storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    import smtplib

    from word_of_the_day.email_sender import DailyEmailLimitExceededError

    # Configure max emails per day to 1
    monkeypatch.setattr(settings, "smtp_max_emails_per_day", 1)
    monkeypatch.setattr(settings, "smtp_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_use_ssl", False)
    monkeypatch.setattr(settings, "smtp_use_tls", False)
    monkeypatch.setattr(settings, "smtp_admin_notification_email", None)

    # Subscribe two users
    temp_storage.add_subscription("smtp1@example.com", "token_smtp1")
    temp_storage.add_subscription("smtp2@example.com", "token_smtp2")

    record = {
        "date": "2026-07-17",
        "word": "tenacity",
        "definition": "(noun) Persistent determination.",
        "source": "Wikipedia",
        "score": 3.9,
        "origin": "Latin tenax",
        "extra_info": None,
        "cluster_id": None,
    }

    # Mock smtplib.SMTP
    sent_emails = []

    class DummySMTP:
        def __init__(self, *args, **kwargs):
            pass

        def ehlo(self, *args, **kwargs):
            pass

        def login(self, *args, **kwargs):
            pass

        def send_message(self, msg):
            sent_emails.append(msg)

        def quit(self):
            pass

    monkeypatch.setattr(smtplib, "SMTP", DummySMTP)

    from datetime import datetime

    today_str = datetime.now().strftime("%Y-%m-%d")
    assert temp_storage.get_sent_count_for_day(today_str) == 0

    subscribers = temp_storage.get_active_subscribers()
    with pytest.raises(DailyEmailLimitExceededError):
        send_email_batch(subscribers, record, temp_storage)

    # Verify only 1 email was sent via mock SMTP and logged in storage
    assert len(sent_emails) == 1
    assert temp_storage.get_sent_count_for_day(today_str) == 1
    assert temp_storage.has_received_email("2026-07-17", "smtp1@example.com")
    assert not temp_storage.has_received_email("2026-07-17", "smtp2@example.com")


def test_email_batch_limit_capping_with_alert(
    temp_storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    from word_of_the_day.email_sender import DailyEmailLimitExceededError

    # Configure max emails per day to 1 and set admin notification email
    monkeypatch.setattr(settings, "smtp_max_emails_per_day", 1)
    monkeypatch.setattr(settings, "smtp_backend", "console")
    monkeypatch.setattr(settings, "smtp_admin_notification_email", "admin@example.com")

    # Subscribe two users
    temp_storage.add_subscription("alert1@example.com", "token_a1")
    temp_storage.add_subscription("alert2@example.com", "token_a2")

    record = {
        "date": "2026-07-17",
        "word": "alertness",
        "definition": "(noun) State of being alert.",
        "source": "Wikipedia",
        "score": 4.1,
        "origin": "French alerte",
        "extra_info": None,
        "cluster_id": None,
    }

    subscribers = temp_storage.get_active_subscribers()

    # Verify DailyEmailLimitExceededError is raised
    with pytest.raises(DailyEmailLimitExceededError) as exc_info:
        send_email_batch(subscribers, record, temp_storage)

    assert "Daily email limit of 1 reached" in str(exc_info.value)

    # Check database: 1 email sent, 1 email blocked
    assert temp_storage.has_received_email("2026-07-17", "alert1@example.com")
    assert not temp_storage.has_received_email("2026-07-17", "alert2@example.com")

    # Check alert email was generated in logs/sent_emails/
    project_root = Path(__file__).resolve().parent.parent
    alert_file = (
        project_root / "logs" / "sent_emails" / "alert_2026-07-17_limit_reached.txt"
    )
    assert alert_file.exists()
    alert_content = alert_file.read_text(encoding="utf-8")
    assert "To: admin@example.com" in alert_content
    assert "[Alert] Daily Email Limit Reached" in alert_content
    assert "limit of 1 has been reached" in alert_content


def test_api_admin_send_email_limit_429(
    client: TestClient, temp_storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Configure max emails per day to 1
    monkeypatch.setattr(settings, "smtp_max_emails_per_day", 1)
    monkeypatch.setattr(settings, "smtp_backend", "console")

    # Subscribe two users
    temp_storage.add_subscription("api1@example.com", "token_api1")
    temp_storage.add_subscription("api2@example.com", "token_api2")

    # Save a word of the day record so send_daily_emails doesn't fail on missing word
    temp_storage.save_word_of_the_day(
        date="2026-07-17",
        word="vigilance",
        definition="State of keeping careful watch.",
        source="Wikipedia",
        score=4.0,
    )

    from word_of_the_day.api import verify_admin

    app.dependency_overrides[verify_admin] = lambda: True

    try:
        # Call the endpoint
        response = client.post(
            "/api/admin/send-email", json={"date": "2026-07-17", "force": False}
        )
        assert response.status_code == 429
        assert "Daily email limit reached" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_email_mime_headers_and_multipart_parts(
    temp_storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    import smtplib

    monkeypatch.setattr(settings, "smtp_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_use_ssl", False)
    monkeypatch.setattr(settings, "smtp_use_tls", False)
    monkeypatch.setattr(settings, "app_base_url", "https://example.com")

    temp_storage.add_subscription("test@example.com", "token_test_123")

    record = {
        "date": "2026-07-17",
        "word": "tenacity",
        "definition": "(noun) Persistent determination.",
        "source": "Wikipedia",
        "score": 3.9,
        "origin": "Latin tenax",
        "extra_info": None,
        "cluster_id": None,
    }

    sent_emails = []

    class DummySMTP:
        def __init__(self, *args, **kwargs):
            pass

        def ehlo(self, *args, **kwargs):
            pass

        def login(self, *args, **kwargs):
            pass

        def send_message(self, msg):
            sent_emails.append(msg)

        def quit(self):
            pass

    monkeypatch.setattr(smtplib, "SMTP", DummySMTP)

    subscribers = temp_storage.get_active_subscribers()
    send_email_batch(subscribers, record, temp_storage)

    assert len(sent_emails) == 1
    msg = sent_emails[0]

    # Verify custom deliverability headers are present for https URL
    assert msg["List-Unsubscribe"] is not None
    assert "token_test_123" in msg["List-Unsubscribe"]
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"

    # Verify multipart/alternative structure has 2 payloads (text/plain and text/html)
    assert msg.is_multipart()
    payloads = msg.get_payload()
    assert len(payloads) == 2

    # First payload should be text/plain
    assert payloads[0].get_content_type() == "text/plain"
    plain_text = payloads[0].get_payload(decode=True).decode("utf-8")
    assert "Word of the Day •" in plain_text
    assert "TENACITY" in plain_text
    assert "Persistent determination." in plain_text
    assert "Latin tenax" in plain_text
    assert "token_test_123" in plain_text

    # Second payload should be text/html
    assert payloads[1].get_content_type() == "text/html"
    html_text = payloads[1].get_payload(decode=True).decode("utf-8")
    assert "<!DOCTYPE html>" in html_text


def test_api_admin_send_email_duplicate_resend_message(
    client: TestClient, temp_storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "smtp_backend", "console")
    temp_storage.add_subscription("resend@example.com", "token_resend_123")
    temp_storage.save_word_of_the_day(
        date="2026-07-21",
        word="resilience",
        definition="Ability to bounce back.",
        source="Wikipedia",
        score=3.5,
    )

    from word_of_the_day.api import verify_admin

    app.dependency_overrides[verify_admin] = lambda: True

    try:
        # 1st Send
        res1 = client.post("/api/admin/send-email", json={"date": "2026-07-21", "force": False})
        assert res1.status_code == 200
        assert res1.json()["sent_count"] == 1

        # 2nd Send (force=False) -> should return 200 with clear message explaining duplicate check
        res2 = client.post("/api/admin/send-email", json={"date": "2026-07-21", "force": False})
        assert res2.status_code == 200
        assert res2.json()["sent_count"] == 0
        assert "Force Resend" in res2.json()["message"]

        # 3rd Send (force=True) -> should send again
        res3 = client.post("/api/admin/send-email", json={"date": "2026-07-21", "force": True})
        assert res3.status_code == 200
        assert res3.json()["sent_count"] == 1
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_send_email_batch_smtp_error_raises(
    temp_storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    import smtplib

    monkeypatch.setattr(settings, "smtp_backend", "smtp")
    temp_storage.add_subscription("fail@example.com", "token_fail")

    class FailingSMTP:
        def __init__(self, *args, **kwargs):
            raise smtplib.SMTPConnectError(421, "Connection refused")

    monkeypatch.setattr(smtplib, "SMTP", FailingSMTP)

    record = {
        "date": "2026-07-21",
        "word": "failure",
        "definition": "Lack of success.",
        "source": "Dictionary",
        "score": 1.0,
        "origin": None,
        "extra_info": None,
        "cluster_id": None,
    }

    subscribers = temp_storage.get_active_subscribers()
    with pytest.raises(RuntimeError) as exc_info:
        send_email_batch(subscribers, record, temp_storage)

    assert "SMTP failure" in str(exc_info.value)

