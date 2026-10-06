"""Small at-least-once SMTP worker for local demo and modest deployment."""

from datetime import timedelta
from email.message import EmailMessage
import smtplib
import time

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .invitations import expire_due_invitations
from .models import MailOutbox, now


def deliver_one() -> bool:
    with SessionLocal() as db:
        message = db.scalar(select(MailOutbox).where(MailOutbox.sent_at.is_(None),
                                                    MailOutbox.next_attempt_at <= now())
                            .order_by(MailOutbox.created_at).limit(1))
        if message is None:
            return False
        email = EmailMessage()
        email["From"] = settings.smtp_from
        email["To"] = message.recipient
        email["Subject"] = message.subject
        email.set_content(message.body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5) as smtp:
                smtp.send_message(email)
            message.sent_at = now()
            message.body = "[delivered]"  # Do not retain verification links after delivery.
            message.last_error = None
        except (OSError, smtplib.SMTPException) as exc:
            message.attempts += 1
            message.last_error = type(exc).__name__[:200]
            delay = min(300, 10 * 2 ** min(message.attempts, 5))
            message.next_attempt_at = now()+timedelta(seconds=delay)
        db.commit()
        return True


def expire_invitations() -> int:
    with SessionLocal() as db:
        expired = expire_due_invitations(db, now())
        db.commit()
        return expired


def main() -> None:
    while True:
        expire_invitations()
        if not deliver_one():
            time.sleep(3)


if __name__ == "__main__":
    main()
