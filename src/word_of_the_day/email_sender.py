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

from .config import settings
from .logger import get_logger
from .storage import Storage, WordOfTheDayRecord

logger = get_logger(__name__)


def parse_definition_and_pos(definition_str: str | None) -> tuple[str, str]:
    """
    Parses definition and part of speech from the definition string.
    Expected format: "(partOfSpeech) Definition text"
    """
    if not definition_str:
        return "No definition found.", "unknown"
    pos_match = re.match(r"^\(([^)]+)\)\s*(.*)", definition_str)
    if pos_match:
        return pos_match.group(2), pos_match.group(1)
    return definition_str, "unknown"


def render_word_email(record: WordOfTheDayRecord, unsubscribe_url: str) -> str:
    """
    Renders the Word of the Day email template with completely inline CSS styles.
    """
    word = record["word"].upper()
    raw_definition = record["definition"]
    definition, part_of_speech = parse_definition_and_pos(raw_definition)
    source = record["source"]
    origin = record.get("origin") or ""

    # Parse and format date
    try:
        dt = datetime.strptime(record["date"], "%Y-%m-%d")
        friendly_date = dt.strftime("%A, %B %d, %Y")
    except ValueError:
        friendly_date = record["date"]

    # Parse score
    extra = record.get("extra_info")
    if record["score"] is not None:
        score_val = f"{record['score']:.4f}"
    elif extra is not None and isinstance(extra.get("zipf_score"), int | float):
        score_val = f"Zipf: {extra['zipf_score']:.2f}"
    else:
        score_val = "-"

    # Conditional origin box
    origin_section = ""
    if origin.strip() and origin.strip().lower() != "not available":
        origin_section = f"""
          <tr>
            <td style="padding-bottom: 28px;">
              <div style="background-color: rgba(255, 255, 255, 0.02); border: 1px solid rgba(209, 178, 128, 0.15); border-radius: 12px; padding: 16px;">
                <span style="font-size: 11px; font-weight: 600; text-transform: uppercase; color: #71717a; display: block; margin-bottom: 4px; letter-spacing: 0.05em; font-family: 'JetBrains Mono', monospace;">Etymology & Origin</span>
                <span style="font-size: 14px; color: #d4d4d8; line-height: 1.5;">{origin}</span>
              </div>
            </td>
          </tr>
        """

    # Obsidian Gold inline style template
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Word of the Day: {word}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #08080a; color: #f4f4f5; font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; -webkit-font-smoothing: antialiased; line-height: 1.6;">
  <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #08080a; padding: 40px 20px;">
    <tr>
      <td align="center">
        <!-- Main Email Card -->
        <table class="card" width="100%" max-width="600" border="0" cellspacing="0" cellpadding="0" style="max-width: 600px; background-color: #121216; border: 1px solid rgba(209, 178, 128, 0.22); border-radius: 24px; padding: 44px; text-align: left; box-shadow: 0 4px 30px rgba(0, 0, 0, 0.4);">
          <!-- Header -->
          <tr>
            <td style="padding-bottom: 20px; border-bottom: 1px solid rgba(209, 178, 128, 0.15);">
              <span style="font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 500; color: #71717a; text-transform: uppercase; letter-spacing: 0.08em;">Word of the Day • {friendly_date}</span>
            </td>
          </tr>
          <!-- Word Title and POS -->
          <tr>
            <td style="padding: 28px 0;">
              <table border="0" cellspacing="0" cellpadding="0">
                <tr>
                  <td style="font-family: 'Playfair Display', Georgia, Times, 'Times New Roman', serif; font-size: 48px; font-weight: 700; color: #f4f4f5; line-height: 1.1; text-transform: lowercase;">
                    {word}
                  </td>
                  <td style="padding-left: 15px; vertical-align: middle;">
                    <span style="font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 500; color: #d1b280; background-color: rgba(209, 178, 128, 0.08); border: 1px solid rgba(209, 178, 128, 0.25); padding: 2px 10px; border-radius: 9999px; text-transform: lowercase;">{part_of_speech}</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <!-- Definition -->
          <tr>
            <td style="font-size: 16px; color: #d4d4d8; line-height: 1.6; padding-bottom: 28px;">
              {definition}
            </td>
          </tr>
          <!-- Origin Section -->
          {origin_section}
          <!-- Footer Details -->
          <tr>
            <td style="padding-top: 20px; border-top: 1px solid rgba(209, 178, 128, 0.15);">
              <table width="100%" border="0" cellspacing="0" cellpadding="0">
                <tr>
                  <td>
                    <span style="font-size: 11px; color: #71717a; text-transform: uppercase; display: block; font-family: 'JetBrains Mono', monospace;">Discovery Source</span>
                    <span style="font-size: 14px; color: #d4d4d8; font-weight: 500;">{source}</span>
                  </td>
                  <td align="right">
                    <span style="font-size: 11px; color: #71717a; text-transform: uppercase; display: block; font-family: 'JetBrains Mono', monospace;">Word Score</span>
                    <span style="font-size: 14px; color: #d1b280; font-weight: 500;">{score_val}</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>

        <!-- Unsubscribe Footer -->
        <table width="100%" max-width="600" border="0" cellspacing="0" cellpadding="0" style="max-width: 600px; text-align: center; margin-top: 24px;">
          <tr>
            <td style="font-size: 12px; color: #71717a; line-height: 1.5;">
              You are receiving this because you subscribed to the word. daily digest.<br>
              <a href="{unsubscribe_url}" style="color: #d1b280; text-decoration: underline; margin-top: 8px; display: inline-block;">Unsubscribe from this list</a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    return html


def send_email_batch(
    recipients: list[dict[str, Any]], record: WordOfTheDayRecord, storage: Storage
) -> int:
    """
    Sends the Word of the Day email to a list of recipients.
    Reuses a single SMTP connection for efficiency and logs deliveries transactionally.
    """
    subject = f"Word of the Day: {record['word'].lower()}"
    app_base_url = settings.app_base_url.rstrip("/")
    sent_count = 0

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

            html_content = render_word_email(record, unsubscribe_url)

            # Prevent double send
            if storage.has_received_email(record["date"], email):
                logger.debug(
                    f"Subscriber {email} already received daily email. Skipping."
                )
                continue

            # Write HTML email preview to file
            email_hash = hashlib.md5(email.encode("utf-8")).hexdigest()[:8]
            preview_file = sent_dir / f"{record['date']}_{email_hash}.html"
            try:
                preview_file.write_text(html_content, encoding="utf-8")
                logger.info(f"[Console Email] Saved preview to {preview_file}")
                storage.log_individual_dispatch(record["date"], email)
                sent_count += 1
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
            if storage.has_received_email(record["date"], email):
                logger.debug(
                    f"Subscriber {email} already received daily email. Skipping."
                )
                continue

            html_content = render_word_email(record, unsubscribe_url)

            # Construct MIME message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
            msg["To"] = email
            msg.attach(MIMEText(html_content, "html"))

            try:
                server.send_message(msg)
                logger.info(f"Successfully sent daily email to {email}")
                storage.log_individual_dispatch(record["date"], email)
                sent_count += 1
            except Exception as e:
                logger.error(f"Error sending daily email to subscriber {email}: {e}")

    except Exception as e:
        logger.error(f"SMTP Connection failure during batch send: {e}", exc_info=True)
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass

    return sent_count


def send_daily_emails(date_str: str, storage: Storage) -> int:
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
    sent = send_email_batch(subscribers, record, storage)
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
