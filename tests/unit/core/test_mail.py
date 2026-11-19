"""Transactional email layout (core/mail.py): text and HTML parts, escaping, multipart."""

import pytest

from app.core import mail
from app.core.config import settings
from app.core.mail import Email
from app.modules.auth import emails as auth_emails
from app.modules.members import emails as member_emails

EMAIL = Email(
    subject="Atur ulang kata sandi Fluctuz",
    paragraphs=["Satu", "Dua <b>tebal</b> & lain-lain"],
    button_label="Buka",
    button_url="https://app.test/login/reset-password?token=abc&x=1",
    notes=["Abaikan bila bukan Anda."],
)


def test_text_part_has_every_line_and_the_bare_link() -> None:
    text = EMAIL.text()
    assert text.startswith("Halo,\n\nSatu\n\nDua <b>tebal</b> & lain-lain\n\n")
    assert "https://app.test/login/reset-password?token=abc&x=1" in text
    assert text.endswith("Abaikan bila bukan Anda.\n\nTim Fluctuz\n")


def test_html_part_escapes_content_and_links_the_button() -> None:
    html = EMAIL.html()
    assert "Dua &lt;b&gt;tebal&lt;/b&gt; &amp; lain-lain" in html
    assert "<b>tebal</b>" not in html
    assert 'href="https://app.test/login/reset-password?token=abc&amp;x=1"' in html
    assert ">Buka</a>" in html and "Abaikan bila bukan Anda." in html
    assert "<title>Atur ulang kata sandi Fluctuz</title>" in html


def test_without_button_there_is_no_link() -> None:
    plain = Email(subject="S", paragraphs=["P"])
    assert "<a " not in plain.html()
    assert plain.text() == "Halo,\n\nP\n\nTim Fluctuz\n"


@pytest.mark.parametrize(
    "email",
    [
        auth_emails.verify_email("tok"),
        auth_emails.reset_password("tok"),
        auth_emails.already_registered(),
        member_emails.invite(token="tok", workspace_name="Dinas", role="reviewer", inviter=None),
    ],
    ids=["verify", "reset", "already-registered", "invite"],
)
def test_every_template_puts_the_same_link_in_both_parts(email: Email) -> None:
    assert email.button_url is not None
    assert email.button_url.startswith(settings.app_base_url.rstrip("/"))
    assert email.button_url in email.text()
    assert f'href="{email.button_url}"' in email.html()


async def test_send_email_builds_multipart_alternative(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(mail, "_send", sent.append)

    await mail.send("budi@contoh.id", EMAIL)

    (message,) = sent
    assert message.get_content_type() == "multipart/alternative"
    text, html = message.get_payload()
    assert (text.get_content_type(), html.get_content_type()) == ("text/plain", "text/html")
    assert "token=abc&x=1" in text.get_content()
    assert "Tim Fluctuz" in html.get_content()
    assert message["To"] == "budi@contoh.id"


async def test_send_email_without_html_stays_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(mail, "_send", sent.append)

    await mail.send_email("budi@contoh.id", "Subjek", "Isi")

    assert sent[0].get_content_type() == "text/plain"


async def test_development_email_reaches_the_log_when_smtp_is_off(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The sign-up link must be readable from the API output in development (no SMTP).

    caplog only receives the record if the `app` logger is enabled for INFO, which uvicorn
    alone does not do; `configure_logging` (called by create_app) does.
    """
    import logging

    assert logging.getLogger("app").handlers, "create_app() must call configure_logging()"
    monkeypatch.setattr(settings, "smtp_host", "")
    await mail.send("budi@contoh.id", auth_emails.verify_email("tok123"))
    assert "/login/verify-email?token=tok123" in caplog.text
