# src/word_of_the_day/email_sender.py
import hashlib
import re
import smtplib
import subprocess
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo  # type: ignore

from jinja2 import Environment, FileSystemLoader

from .config import settings
from .logger import get_logger
from .storage import Storage, WordOfTheDayRecord

logger = get_logger(__name__)

jinja_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=True,
)


class DailyEmailLimitExceededError(ValueError):
    """Exception raised when the daily email dispatch limit is reached."""

    pass


def parse_definition_and_pos(definition_str: str | None) -> tuple[str, str]:
    """
    Parses definition and part of speech from the definition string.
    Expected format: "(partOfSpeech) Definition text" or "(partOfSpeech) : Definition text"
    """
    if not definition_str:
        return "No definition found.", "unknown"
    pos_match = re.match(r"^\(([^)]+)\)\s*:?\s*(.*)", definition_str)
    if pos_match:
        return pos_match.group(2).strip(), pos_match.group(1)
    return definition_str.strip(), "unknown"


def render_word_email(record: WordOfTheDayRecord, unsubscribe_url: str) -> str:
    """
    Renders an HTML email for the given word record using Jinja2 template.
    """
    word = record["word"]
    def_str = record["definition"] or "No definition available."
    origin = record["origin"] or ""
    source = record["source"] or "Word of the Day"

    definition, part_of_speech = parse_definition_and_pos(def_str)

    # Format friendly date
    try:
        dt = datetime.strptime(record["date"], "%Y-%m-%d")
        friendly_date = dt.strftime("%A, %B %d, %Y")
    except ValueError:
        friendly_date = record["date"]

    # Parse score
    extra = record.get("extra_info")
    if record["score"] is not None:
        if record["score"] > 1.0:
            score_val = f"Zipf: {record['score']:.2f}"
        else:
            score_val = f"{record['score']:.4f}"
    elif extra is not None and isinstance(extra.get("zipf_score"), int | float):
        score_val = f"Zipf: {extra['zipf_score']:.2f}"
    else:
        score_val = "-"

    template = jinja_env.get_template("emails/daily_digest.html")
    return template.render(
        word=word,
        part_of_speech=part_of_speech,
        definition=definition,
        origin=origin,
        source=source,
        score_val=score_val,
        friendly_date=friendly_date,
        unsubscribe_url=unsubscribe_url,
    )


def render_word_plain_text(record: WordOfTheDayRecord, unsubscribe_url: str) -> str:
    """
    Renders the Word of the Day email in plain text format.
    """
    word = record["word"].upper()
    raw_definition = record["definition"]
    definition, part_of_speech = parse_definition_and_pos(raw_definition)
    source = record["source"]
    origin = record.get("origin") or ""

    try:
        dt = datetime.strptime(record["date"], "%Y-%m-%d")
        friendly_date = dt.strftime("%A, %B %d, %Y")
    except ValueError:
        friendly_date = record["date"]

    extra = record.get("extra_info")
    if record["score"] is not None:
        if record["score"] > 1.0:
            score_val = f"Zipf: {record['score']:.2f}"
        else:
            score_val = f"{record['score']:.4f}"
    elif extra is not None and isinstance(extra.get("zipf_score"), int | float):
        score_val = f"Zipf: {extra['zipf_score']:.2f}"
    else:
        score_val = "-"

    text = f"Word of the Day • {friendly_date}\n\n"
    text += f"{word} ({part_of_speech})\n"
    text += f"Definition: {definition}\n\n"
    if origin.strip() and origin.strip().lower() != "not available":
        text += f"Etymology & Origin:\n{origin}\n\n"
    text += f"Discovery Source: {source}\n"
    text += f"Word Score: {score_val}\n\n"
    text += "You are receiving this because you subscribed to the word. daily digest.\n"
    text += f"Unsubscribe from this list: {unsubscribe_url}\n"
    return text


def send_limit_alert_email(
    date_str: str,
    limit: int,
    smtp_server: smtplib.SMTP | None = None,
) -> None:
    """
    Sends an alert email to the configured administrator when the daily email limit is reached.
    """
    admin_email = settings.smtp_admin_notification_email
    if not admin_email:
        logger.info("No admin notification email configured. Skipping alert email.")
        return

    subject = f"[Alert] Daily Email Limit Reached ({date_str})"
    body = (
        f"Warning: The daily email dispatch limit of {limit} has been reached "
        f"for the date {date_str}.\n\n"
        f"Some subscribers did not receive their daily email.\n"
        f"To allow more emails to be sent, please increase the SMTP_MAX_EMAILS_PER_DAY "
        f"value in your configuration/environment variables."
    )

    if settings.smtp_backend == "console":
        logger.info(f"[Console Alert Email] Sending alert to {admin_email}: {subject}")
        project_root = Path(__file__).resolve().parent.parent.parent
        sent_dir = project_root / "logs" / "sent_emails"
        sent_dir.mkdir(parents=True, exist_ok=True)
        alert_file = sent_dir / f"alert_{date_str}_limit_reached.txt"
        try:
            alert_file.write_text(
                f"To: {admin_email}\nSubject: {subject}\n\n{body}", encoding="utf-8"
            )
            logger.info(f"[Console Alert Email] Saved alert preview to {alert_file}")
        except Exception as e:
            logger.error(f"Failed writing console alert email: {e}")
        return

    logger.info(f"Sending SMTP alert email to {admin_email}...")
    try:
        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        msg["To"] = admin_email

        local_server = smtp_server
        should_close = False
        if not local_server:
            if settings.smtp_use_ssl:
                local_server = smtplib.SMTP_SSL(
                    settings.smtp_host, settings.smtp_port, timeout=10
                )
            else:
                local_server = smtplib.SMTP(
                    settings.smtp_host, settings.smtp_port, timeout=10
                )

            local_server.ehlo()
            if settings.smtp_use_tls and not settings.smtp_use_ssl:
                local_server.starttls()
                local_server.ehlo()

            if settings.smtp_username and settings.smtp_password:
                local_server.login(settings.smtp_username, settings.smtp_password)
            should_close = True

        local_server.send_message(msg)
        logger.info(f"Successfully sent daily limit alert email to {admin_email}")

        if should_close and local_server:
            try:
                local_server.quit()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Failed to send daily limit alert email: {e}", exc_info=True)


def send_email_batch(
    recipients: list[dict[str, Any]],
    record: WordOfTheDayRecord,
    storage: Storage,
    force: bool = False,
) -> int:
    """
    Sends the Word of the Day email to a list of recipients.
    Reuses a single SMTP connection for efficiency and logs deliveries transactionally.
    """
    subject = f"Word of the Day: {record['word'].upper()}"
    app_base_url = settings.app_base_url.rstrip("/")
    sent_count = 0

    today_str = datetime.now().strftime("%Y-%m-%d")
    sent_today = storage.get_sent_count_for_day(today_str)

    if settings.smtp_backend == "console":
        logger.info("Using console SMTP backend. Generating previews...")
        # Resolve sent_emails dir relative to project root
        project_root = Path(__file__).resolve().parent.parent.parent
        sent_dir = project_root / "logs" / "sent_emails"
        sent_dir.mkdir(parents=True, exist_ok=True)

        for subscriber in recipients:
            email = subscriber["email"]
            token = subscriber["unsubscribe_token"]
            unsubscribe_url = f"{app_base_url}/api/unsubscribe?token={token}"

            # Prevent double send
            if not force and storage.has_received_email(record["date"], email):
                logger.debug(
                    f"Subscriber {email} already received daily email. Skipping."
                )
                continue

            # Check daily cap
            if sent_today >= settings.smtp_max_emails_per_day:
                logger.warning(
                    f"Daily email limit reached ({settings.smtp_max_emails_per_day}). Stopping console dispatch."
                )
                send_limit_alert_email(record["date"], settings.smtp_max_emails_per_day)
                raise DailyEmailLimitExceededError(
                    f"Daily email limit of {settings.smtp_max_emails_per_day} reached. Dispatch halted."
                )

            html_content = render_word_email(record, unsubscribe_url)

            # Write HTML email preview to file
            email_hash = hashlib.md5(email.encode("utf-8")).hexdigest()[:8]
            preview_file = sent_dir / f"{record['date']}_{email_hash}.html"
            try:
                preview_file.write_text(html_content, encoding="utf-8")
                logger.info(f"[Console Email] Saved preview to {preview_file}")
                storage.log_individual_dispatch(record["date"], email)
                sent_count += 1
                sent_today += 1
            except Exception as e:
                logger.error(
                    f"Failed writing console email preview to {preview_file}: {e}"
                )
        return sent_count

    # SMTP Backend
    logger.info(
        f"Connecting to SMTP server at {settings.smtp_host}:{settings.smtp_port}..."
    )
    server: smtplib.SMTP | None = None
    try:
        # Determine connection method
        if settings.smtp_use_ssl:
            server = smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=10
            )
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)

        assert server is not None
        server.ehlo()
        if settings.smtp_use_tls and not settings.smtp_use_ssl:
            server.starttls()
            server.ehlo()

        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password)

        logger.info("SMTP Session initialized. Beginning batch dispatch...")

        for subscriber in recipients:
            email = subscriber["email"]
            token = subscriber["unsubscribe_token"]
            unsubscribe_url = f"{app_base_url}/api/unsubscribe?token={token}"

            # Prevent double send
            if not force and storage.has_received_email(record["date"], email):
                logger.debug(
                    f"Subscriber {email} already received daily email. Skipping."
                )
                continue

            # Check daily cap
            if sent_today >= settings.smtp_max_emails_per_day:
                logger.warning(
                    f"Daily email limit reached ({settings.smtp_max_emails_per_day}). Stopping SMTP dispatch."
                )
                send_limit_alert_email(
                    record["date"], settings.smtp_max_emails_per_day, smtp_server=server
                )
                raise DailyEmailLimitExceededError(
                    f"Daily email limit of {settings.smtp_max_emails_per_day} reached. Dispatch halted."
                )

            html_content = render_word_email(record, unsubscribe_url)

            # Construct MIME message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
            msg["To"] = email

            # Add List-Unsubscribe headers only when using a public HTTPS URL (avoid breaking delivery with localhost URLs or legacy Precedence headers)
            if (
                unsubscribe_url.startswith("https://")
                and "localhost" not in unsubscribe_url
                and "127.0.0.1" not in unsubscribe_url
            ):
                msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
                msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

            # Attach plain text version first
            plain_content = render_word_plain_text(record, unsubscribe_url)
            msg.attach(MIMEText(plain_content, "plain"))

            # Attach HTML version second
            msg.attach(MIMEText(html_content, "html"))

            try:
                server.send_message(msg)
                logger.info(f"Successfully sent daily email to {email}")
                storage.log_individual_dispatch(record["date"], email)
                sent_count += 1
                sent_today += 1
            except Exception as e:
                logger.error(f"Error sending daily email to subscriber {email}: {e}")

    except Exception as e:
        if isinstance(e, DailyEmailLimitExceededError):
            raise
        logger.error(f"SMTP Connection failure during batch send: {e}", exc_info=True)
        raise RuntimeError(f"SMTP failure: {e}") from e
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass

    return sent_count


def send_daily_emails(date_str: str, storage: Storage, force: bool = False) -> int:
    """
    Coordinates daily email dispatch for a specific date.
    Triggers word generation if missing, fetches active subscribers, and dispatches.
    """
    logger.info(f"Initiating daily email dispatch routine for date: {date_str}")
    record = storage.get_word_of_the_day(date_str)

    if not record:
        logger.warning(
            f"Word of the Day record not found for {date_str}. Triggering auto pipeline..."
        )
        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "word_of_the_day.cli",
                    "--mode",
                    "auto",
                    "--date",
                    date_str,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            # Re-fetch after generation
            record = storage.get_word_of_the_day(date_str)
        except Exception as e:
            logger.error(
                f"Failed to automatically generate Word of the Day for {date_str}: {e}"
            )
            return 0

    if not record:
        logger.error(
            f"Cannot dispatch emails: Word of the Day generation failed for {date_str}."
        )
        return 0

    subscribers = storage.get_active_subscribers()
    if not subscribers:
        logger.info("No active email subscriptions found. Skipping dispatch.")
        return 0

    logger.info(f"Found {len(subscribers)} active subscribers. Starting batch...")
    sent = send_email_batch(subscribers, record, storage, force=force)
    logger.info(
        f"Daily email dispatch completed. Sent: {sent}/{len(subscribers)} emails."
    )
    return sent


def check_and_send_daily_emails() -> None:
    """
    Triggered by the scheduler or manual invocation.
    Determines if it is past 6:00 AM (in America/Chicago timezone) and dispatches emails if not already done.
    """
    try:
        tz = zoneinfo.ZoneInfo("America/Chicago")
    except Exception:
        try:
            tz = zoneinfo.ZoneInfo("UTC")
        except Exception:
            tz = None

    now = datetime.now(tz)
    date_str = now.strftime("%Y-%m-%d")

    # Only send emails if current time is past 6:00 AM local time
    if now.hour < 6:
        logger.debug(
            f"Current local time ({now.isoformat()}) is before 6:00 AM. Skipping dispatch."
        )
        return

    storage = Storage()
    subscribers = storage.get_active_subscribers()
    if not subscribers:
        return

    # Check if there's any active subscriber who hasn't received the email yet for today
    pending_subscribers = [
        s for s in subscribers if not storage.has_received_email(date_str, s["email"])
    ]
    if not pending_subscribers:
        logger.debug(
            f"All active subscribers have already received today's email for {date_str}."
        )
        return

    logger.info(
        f"Dispatched email check: pending recipients found for date {date_str}. Launching dispatch..."
    )
    send_daily_emails(date_str, storage)
