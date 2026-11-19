"""POST /webhooks/telegram end to end: secret, idempotency, isolation, order, delivery status.

Jobs run inline (QUEUE_INLINE) on the test session; the Bot API is a recording fake.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import session as db_session
from app.modules.channels import telegram
from app.modules.channels.telegram import TelegramError
from app.modules.conversations.engine import copy
from app.modules.conversations.engine.types import Outbound
from app.modules.conversations.models import Conversation, Message
from app.modules.extension_workers.models import ExtensionWorker
from app.modules.workspaces.models import Workspace
from tests.telegram_fixtures import telegram_update

SECRET = "s3cret-webhook-token"
URL = "/webhooks/telegram"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}


@dataclass
class FakeTelegram:
    sent: list[tuple[str, Outbound]] = field(default_factory=list)
    answered: list[str] = field(default_factory=list)
    left: list[str] = field(default_factory=list)
    fail_with: TelegramError | None = None

    async def send(self, chat_id: str, out: Outbound) -> str:
        if self.fail_with:
            raise self.fail_with
        self.sent.append((chat_id, out))
        return str(100 + len(self.sent))

    async def answer_callback(self, callback_id: str) -> None:
        self.answered.append(callback_id)

    async def leave_chat(self, chat_id: str) -> None:
        self.left.append(chat_id)


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


async def _post(
    client: AsyncClient, update: dict[str, Any], headers: dict[str, str] = HEADERS
) -> int:
    return (await client.post(URL, json=update, headers=headers)).status_code


async def _messages(db: AsyncSession, direction: str) -> list[Message]:
    rows = await db.scalars(
        select(Message).where(Message.direction == direction).order_by(Message.created_at)
    )
    return list(rows)


async def test_off_without_a_secret(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_webhook_secret", "")
    assert await _post(client, telegram_update("text")) == 404


@pytest.mark.parametrize("headers", [{}, {"X-Telegram-Bot-Api-Secret-Token": "salah"}])
async def test_wrong_secret_is_refused(
    client: AsyncClient, bot: FakeTelegram, db: AsyncSession, headers: dict[str, str]
) -> None:
    assert await _post(client, telegram_update("text"), headers) == 401
    assert await _messages(db, "in") == []


async def test_oversized_body_is_refused(client: AsyncClient, bot: FakeTelegram) -> None:
    update = telegram_update("text")
    update["message"]["text"] = "x" * 300_000
    assert await _post(client, update) == 413


async def test_broken_json_is_acknowledged(client: AsyncClient, bot: FakeTelegram) -> None:
    response = await client.post(URL, content=b"{not json", headers=HEADERS)
    assert response.status_code == 200  # an error would make Telegram resend it forever


async def test_same_update_twice_is_stored_and_answered_once(
    client: AsyncClient, bot: FakeTelegram, db: AsyncSession
) -> None:
    update = telegram_update("text")
    assert await _post(client, update) == 200
    assert await _post(client, update) == 200
    inbound = await _messages(db, "in")
    assert len(inbound) == 1
    assert inbound[0].processed_at is not None
    assert len(bot.sent) == 1


async def test_unbound_chat_gets_join_instructions_and_creates_nothing(
    client: AsyncClient, bot: FakeTelegram, db: AsyncSession
) -> None:
    assert await _post(client, telegram_update("text")) == 200
    assert bot.sent == [("700100200", Outbound(copy.JOIN_FIRST))]
    (inbound,) = await _messages(db, "in")
    (outbound,) = await _messages(db, "out")
    assert inbound.workspace_id is None and inbound.conversation_id is None
    assert (outbound.delivery_status, outbound.external_id) == ("sent", "message:700100200:101")
    assert await db.scalar(select(func.count()).select_from(Conversation)) == 0


async def test_messages_are_processed_in_send_order(
    client: AsyncClient, bot: FakeTelegram, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.conversations import jobs

    queued: list[tuple[str, str]] = []

    async def hold(channel_id: str, chat_id: str) -> None:
        queued.append((channel_id, chat_id))

    # Two updates arrive before the worker runs; the second was sent in the same second.
    monkeypatch.setattr(jobs.process_chat_job, "kiq", hold)
    first = telegram_update("text", update_id=510000020)
    second = telegram_update("edited_text", update_id=510000019)
    second["edited_message"]["date"] = first["message"]["date"]
    later = telegram_update("text", update_id=510000018)
    later["message"]["date"] += 5
    for u in (later, first, second):
        assert await _post(client, u) == 200

    await jobs.process_chat_job.original_func(*queued[0])  # type: ignore[attr-defined]
    inbound = await _messages(db, "in")
    assert all(m.processed_at is not None for m in inbound)
    # Same second: the lower update id (received first by Telegram) comes first; the burst of
    # three gets the join answer and the edit answer once each, in that order.
    assert [out.text for _, out in bot.sent] == [copy.EDITED, copy.JOIN_FIRST]


async def test_button_taps_are_acknowledged(client: AsyncClient, bot: FakeTelegram) -> None:
    assert await _post(client, telegram_update("callback")) == 200
    assert bot.answered == ["4382bfdwdsb323b2d9"]


async def test_groups_are_ignored_and_left(
    client: AsyncClient, bot: FakeTelegram, db: AsyncSession
) -> None:
    assert await _post(client, telegram_update("group_text")) == 200
    assert await _post(client, telegram_update("added_to_group")) == 200
    assert await _messages(db, "in") == []
    assert bot.sent == []
    assert bot.left == ["-1001234567890"]


async def test_timeout_is_uncertain_and_not_resent(
    client: AsyncClient, bot: FakeTelegram, db: AsyncSession
) -> None:
    bot.fail_with = TelegramError(None, "timeout", timed_out=True)
    assert await _post(client, telegram_update("text")) == 200
    (outbound,) = await _messages(db, "out")
    assert (outbound.delivery_status, outbound.attempts) == ("uncertain", 1)


async def test_blocked_bot_marks_the_worker_unreachable(
    client: AsyncClient, bot: FakeTelegram, db: AsyncSession, organization: Workspace
) -> None:
    worker = ExtensionWorker(
        workspace_id=organization.id, name="Budi", telegram_user_id="700100200", status="active"
    )
    db.add(worker)
    await db.flush()
    assert await _post(client, telegram_update("blocked")) == 200
    await db.refresh(worker)
    assert worker.status == "unreachable"


async def test_send_refused_by_telegram_is_failed(
    client: AsyncClient, bot: FakeTelegram, db: AsyncSession
) -> None:
    bot.fail_with = TelegramError(403, "Forbidden: bot was blocked by the user")
    assert await _post(client, telegram_update("text")) == 200
    (outbound,) = await _messages(db, "out")
    assert outbound.delivery_status == "failed"
    assert outbound.error is not None and outbound.error.startswith("403")
