"""Retrying failed sends and the channel log with "Susul yang gagal" (roadmap 7.2)."""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.auth.models import User
from app.modules.channels.telegram import TelegramError
from app.modules.conversations import jobs, service
from app.modules.conversations.models import Message
from app.modules.workspaces.models import Workspace
from tests.api.webhooks.test_telegram_report_flow import Worker, _joined
from tests.conftest import add_member, sign_in
from tests.telegram_fixtures import FakeTelegram


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> Worker:
    return Worker(client, bot)


async def _last_out(db: AsyncSession) -> Message:
    message = await db.scalar(
        select(Message)
        .where(Message.direction == "out")
        .order_by(Message.created_at.desc(), Message.id.desc())
    )
    assert message is not None
    await db.refresh(message)
    return message


async def _failing_reply(
    chat: Worker, db: AsyncSession, organization: Workspace, error: TelegramError
) -> Message:
    await _joined(chat, db, organization)
    chat.bot.fail_with = error
    await chat.say("mulai")
    return await _last_out(db)


async def _retry_now(db: AsyncSession, message: Message) -> None:
    await db.execute(
        update(Message)
        .where(Message.id == message.id)
        .values(retry_at=now_utc() - timedelta(seconds=1))
    )
    await db.flush()
    await jobs.retry_failed_messages_job()
    await db.refresh(message)


async def test_network_failure_is_retried_until_it_is_sent(
    chat: Worker, db: AsyncSession, organization: Workspace, bot: FakeTelegram
) -> None:
    message = await _failing_reply(chat, db, organization, TelegramError(None, "ConnectError"))
    assert (message.delivery_status, message.attempts) == ("failed", 1)
    assert message.retry_at is not None
    assert timedelta(seconds=50) < message.retry_at - now_utc() <= timedelta(minutes=1)

    await jobs.retry_failed_messages_job()  # not yet due
    await db.refresh(message)
    assert message.attempts == 1

    bot.fail_with = None
    await _retry_now(db, message)
    assert (message.delivery_status, message.attempts, message.retry_at) == ("sent", 2, None)


async def test_three_retries_then_it_waits_for_an_admin(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User, bot: FakeTelegram
) -> None:
    message = await _failing_reply(chat, db, organization, TelegramError(502, "Bad Gateway"))
    for _ in range(3):
        await _retry_now(db, message)
    assert (message.delivery_status, message.attempts, message.retry_at) == ("failed", 4, None)

    await sign_in(chat.client, user.email, organization.id)
    body = (await chat.client.get("/api/v1/channels/logs", params={"status": "failed"})).json()
    (item,) = body["data"]
    assert (
        item["id"] == str(message.id) and item["failure"] == "other" and item["retrying"] is False
    )
    assert item["contact"].startswith("•••") and "body" not in item
    assert item["extension_worker"]["name"]

    bot.fail_with = None
    resent = await chat.client.post(f"/api/v1/channels/logs/{message.id}/resend")
    assert resent.status_code == 200, resent.text
    assert resent.json()["data"]["delivery_status"] == "sent"
    again = await chat.client.post(f"/api/v1/channels/logs/{message.id}/resend")
    assert again.status_code == 409
    assert again.json()["errors"][0]["code"] == "message_not_resendable"
    assert (await chat.client.get("/api/v1/channels/logs", params={"status": "failed"})).json()[
        "data"
    ] == []


@pytest.mark.parametrize(
    ("error", "status", "failure"),
    [
        (TelegramError(403, "Forbidden: bot was blocked by the user"), "failed", "blocked"),
        (TelegramError(400, "Bad Request: message is too long"), "failed", "rejected"),
        (TelegramError(None, "timeout", timed_out=True), "uncertain", "timeout"),
    ],
)
async def test_sends_that_must_not_be_retried(
    chat: Worker,
    db: AsyncSession,
    organization: Workspace,
    user: User,
    error: TelegramError,
    status: str,
    failure: str,
) -> None:
    message = await _failing_reply(chat, db, organization, error)
    assert message.delivery_status == status and message.retry_at is None
    await sign_in(chat.client, user.email, organization.id)
    (item,) = (await chat.client.get("/api/v1/channels/logs", params={"status": "failed"})).json()[
        "data"
    ]
    assert item["failure"] == failure


async def test_log_is_admin_only_and_per_workspace(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await _joined(chat, db, organization)
    await chat.say("mulai")
    await sign_in(chat.client, user.email, organization.id)
    page = (await chat.client.get("/api/v1/channels/logs", params={"limit": 2})).json()
    assert len(page["data"]) == 2 and page["meta"]["pagination"]["has_more"] is True
    assert {i["direction"] for i in page["data"]} <= {"in", "out"}

    reviewer = await add_member(db, organization.id, email="rina@example.com", role="reviewer")
    await sign_in(chat.client, reviewer.email, organization.id)
    assert (await chat.client.get("/api/v1/channels/logs")).status_code == 403

    other = Workspace(name="Dinas Pertanian Garut", type="organization")
    db.add(other)
    await db.flush()
    stranger = await add_member(db, other.id, email="ujang@example.com", role="admin")
    await sign_in(chat.client, stranger.email, other.id)
    assert (await chat.client.get("/api/v1/channels/logs")).json()["data"] == []
    message = await _last_out(db)
    response = await chat.client.post(f"/api/v1/channels/logs/{message.id}/resend")
    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "channel_message_not_found"


async def test_held_back_reply_is_not_retried(
    chat: Worker, db: AsyncSession, organization: Workspace, bot: FakeTelegram
) -> None:
    await _joined(chat, db, organization)
    await chat.say("mulai")
    message = await _last_out(db)
    message.delivery_status = "pending"
    assert message.conversation_id is not None
    from app.modules.conversations.models import Conversation

    conversation = await db.get(Conversation, message.conversation_id)
    assert conversation is not None
    conversation.status = "taken_over"
    await db.flush()
    await service.deliver(db, bot, message.id)
    await db.refresh(message)
    assert message.delivery_status == "failed" and message.retry_at is None
