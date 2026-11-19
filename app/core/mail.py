"""Outgoing email over SMTP (STARTTLS): plain text, plus an HTML alternative when given.

Call `send_email` from a FastAPI BackgroundTask so a slow mail server never delays the response.
Build the content with `Email` so the text and HTML parts always say the same thing.
"""

import asyncio
import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from html import escape

from app.core.config import settings

logger = logging.getLogger(__name__)

# Brand colours from the web design system (fredd-frontend design-system.md).
_INK, _ORANGE, _MUTED, _BG, _BORDER = "#14110F", "#F26A1B", "#6B645D", "#F8F6F3", "#ECE6DF"
_FONT = "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


@dataclass(frozen=True)
class Email:
    """One transactional email: greeting, paragraphs, an optional button, then small print."""

    subject: str
    paragraphs: list[str]
    button_label: str | None = None
    button_url: str | None = None
    notes: list[str] = field(default_factory=list)

    def text(self) -> str:
        parts = ["Halo,", *self.paragraphs]
        if self.button_url:
            parts.append(self.button_url)
        parts += [*self.notes, "Tim Fluctuz"]
        return "\n\n".join(parts) + "\n"

    def html(self) -> str:
        p = f"margin:0 0 16px;font:15px/1.6 {_FONT};color:{_INK}"
        body = [f'<p style="{p}">Halo,</p>']
        body += [f'<p style="{p}">{escape(text)}</p>' for text in self.paragraphs]
        if self.button_label and self.button_url:
            url = escape(self.button_url, quote=True)
            body.append(
                '<table role="presentation" cellpadding="0" cellspacing="0" '
                'style="margin:8px 0 24px">'
                f'<tr><td style="border-radius:12px;background:{_ORANGE}">'
                f'<a href="{url}" style="display:inline-block;padding:12px 24px;'
                f'font:600 15px/1.2 {_FONT};color:{_INK};text-decoration:none;border-radius:12px">'
                f"{escape(self.button_label)}</a></td></tr></table>"
                f'<p style="margin:0 0 16px;font:13px/1.6 {_FONT};color:{_MUTED}">'
                f"Jika tombol tidak berfungsi, salin tautan ini ke browser:<br>"
                f'<a href="{url}" style="color:{_MUTED};word-break:break-all">{url}</a></p>'
            )
        small = f"margin:0 0 12px;font:13px/1.6 {_FONT};color:{_MUTED}"
        body += [f'<p style="{small}">{escape(note)}</p>' for note in self.notes]
        body.append(f'<p style="{p};margin:0">Tim Fluctuz</p>')
        return (
            '<!doctype html><html lang="id"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{escape(self.subject)}</title></head>"
            f'<body style="margin:0;padding:0;background:{_BG}">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:{_BG}"><tr><td align="center" style="padding:32px 16px">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="max-width:560px">'
            f'<tr><td style="padding:0 4px 16px;font:800 22px/1 {_FONT};color:{_INK}">'
            f'Fluctuz<span style="color:{_ORANGE}">.</span></td></tr>'
            f'<tr><td style="background:#FFFFFF;border:1px solid {_BORDER};border-radius:16px;'
            f'padding:32px 28px">{"".join(body)}</td></tr>'
            f'<tr><td style="padding:16px 4px;font:12px/1.6 {_FONT};color:{_MUTED}">'
            "Email ini dikirim otomatis oleh Fluctuz. Mohon tidak membalas email ini.</td></tr>"
            "</table></td></tr></table></body></html>"
        )


def _send(message: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


async def send_email(to: str, subject: str, body: str, html: str | None = None) -> None:
    """Never raises: a mail failure must not become a 500 or reveal whether an account exists.

    With `html`, the message is `multipart/alternative` (text first, HTML preferred by clients).
    """
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
    if html is not None:
        message.add_alternative(html, subtype="html")
    try:
        await asyncio.to_thread(_send, message)
    except OSError, smtplib.SMTPException:
        logger.exception("email to %s failed", to)


async def send(to: str, email: Email) -> None:
    """Send an `Email` with both its text and HTML parts.

    `send_email` is looked up at call time, so the `outbox` test fixture still captures it.
    """
    await send_email(to, email.subject, email.text(), email.html())
