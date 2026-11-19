"""Polling mode for development bots (roadmap 3.9): refuses unsafe setups."""

from typing import Any

import pytest

from app.core.config import settings
from app.modules.channels import telegram
from scripts import telegram_poll


class FakeBot:
    def __init__(self, webhook_url: str = "") -> None:
        self.webhook_url = webhook_url

    async def call(self, method: str, **_: Any) -> dict[str, Any]:
        if method == "getMe":
            return {"username": "FluctuzDevBot"}
        return {"url": self.webhook_url}

    async def aclose(self) -> None:
        return None


async def test_refuses_outside_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "staging")
    assert await telegram_poll.main() == 1


async def test_refuses_without_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    assert await telegram_poll.main() == 1


async def test_refuses_a_bot_that_has_a_webhook(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(settings, "telegram_bot_token", "123:dev")
    monkeypatch.setattr(telegram, "get_client", lambda: FakeBot("https://staging.example.com/x"))
    assert await telegram_poll.main() == 1
    assert "webhook" in capsys.readouterr().err
