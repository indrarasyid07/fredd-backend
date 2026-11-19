"""Email goes through the job queue; a mail problem never reaches the caller."""

import pytest

from app.core import mail
from tests.conftest import Outbox


def _email() -> mail.Email:
    return mail.Email(subject="Uji", paragraphs=["Halo"])


async def test_send_queues_the_email_job(outbox: Outbox) -> None:
    await mail.send("dina@contoh.id", _email())
    assert [(to, subject) for to, subject, _ in outbox] == [("dina@contoh.id", "Uji")]
    assert outbox.html[0] is not None


async def test_send_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def broken(to: str, subject: str, body: str, html: str | None = None) -> None:
        calls.append(to)
        raise OSError("smtp down")

    monkeypatch.setattr(mail, "send_email", broken)
    await mail.send("dina@contoh.id", _email())  # no exception reaches the caller
    # The job ran and failed; the worker retries it (inline mode records the failure instead).
    assert calls == ["dina@contoh.id"]
