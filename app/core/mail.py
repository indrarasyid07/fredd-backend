"""Outgoing email over SMTP (STARTTLS). Plain text only.

Call it from a FastAPI BackgroundTask so a slow mail server never delays the response.
"""

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def _send(message: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


async def send_email(to: str, subject: str, body: str) -> None:
    """Never raises: a mail failure must not become a 500 or reveal whether an account exists."""
    if not settings.smtp_host:
        if settings.is_development:
            logger.info(
                "email to %s (SMTP_HOST empty, not sent)\nSubject: %s\n%s", to, subject, body
            )
        else:
            logger.error("email to %s dropped: SMTP_HOST is not configured", to)
        return
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = settings.smtp_from, to, subject
    message.set_content(body)
    try:
        await asyncio.to_thread(_send, message)
    except OSError, smtplib.SMTPException:
        logger.exception("email to %s failed", to)
