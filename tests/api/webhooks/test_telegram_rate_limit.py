"""Anti-spam per chat identity (roadmap 3.6): over the per-minute limit, messages are neither
stored nor processed, and the chat hears about it once."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis
from app.modules.conversations import service
from app.modules.conversations.engine import copy
from app.modules.conversations.models import Message
from tests.api.webhooks.test_telegram_join import Chat
from tests.telegram_fixtures import FakeTelegram

LIMIT = 3


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram, monkeypatch: pytest.MonkeyPatch) -> Chat:
    monkeypatch.setattr(service, "MAX_MESSAGES_PER_MINUTE", LIMIT)
    return Chat(client, bot)


async def _inbound(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).where(Message.direction == "in")) or 0


async def test_over_the_limit_is_dropped_with_one_notice(chat: Chat, db: AsyncSession) -> None:
    for _ in range(LIMIT):
        assert await chat.say("halo") == [copy.JOIN_FIRST]
    assert await chat.say("halo lagi") == [copy.RATE_LIMITED]
    assert await chat.say("dan lagi") == []  # told once per minute
    assert await _inbound(db) == LIMIT
    notices = select(func.count()).where(Message.body == copy.RATE_LIMITED)
    assert await db.scalar(notices) == 1


async def test_the_next_minute_starts_over(chat: Chat, db: AsyncSession) -> None:
    for _ in range(LIMIT + 1):
        await chat.say("halo")
    await redis.flushdb()  # the one-minute window ends
    assert await chat.say("halo") == [copy.JOIN_FIRST]
    assert await _inbound(db) == LIMIT + 1


async def test_buttons_count_too(chat: Chat, db: AsyncSession) -> None:
    for _ in range(LIMIT):
        await chat.tap("join:keep")
    assert await chat.say("halo") == [copy.RATE_LIMITED]
