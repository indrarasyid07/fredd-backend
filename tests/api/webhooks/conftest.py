from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import session as db_session
from app.modules.channels import telegram
from tests.telegram_fixtures import SECRET, FakeTelegram


@pytest.fixture
def bot(monkeypatch: pytest.MonkeyPatch, db: AsyncSession) -> FakeTelegram:
    fake = FakeTelegram()
    monkeypatch.setattr(settings, "telegram_webhook_secret", SECRET)
    monkeypatch.setattr(telegram, "get_client", lambda: fake)

    @asynccontextmanager
    async def test_session() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr(db_session, "open_session", test_session)
    return fake
