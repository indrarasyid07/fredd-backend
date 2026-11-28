"""Jeda agent: Fluctuz stops answering an organization's workers (roadmap 6.6)."""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.auth.models import User
from app.modules.conversations import jobs
from app.modules.conversations.engine import copy
from app.modules.conversations.models import Message
from app.modules.workspaces.models import Workspace
from tests.api.webhooks.test_telegram_report_flow import Worker, _conversation, _joined
from tests.conftest import add_member, sign_in
from tests.telegram_fixtures import FakeTelegram


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> Worker:
    return Worker(client, bot)


async def _set(client: AsyncClient, action: str) -> dict[str, object]:
    response = await client.post(f"/api/v1/agent/{action}")
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_admin_pauses_and_resumes(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await sign_in(client, user.email, organization.id)
    assert (await client.get("/api/v1/agent/status")).json()["data"]["paused"] is False
    paused = await _set(client, "pause")
    assert paused["paused"] is True and paused["paused_by"] == user.name
    assert (await _set(client, "pause"))["paused_at"] == paused["paused_at"]  # twice: no change
    assert (await _set(client, "resume"))["paused"] is False

    reviewer = await add_member(db, organization.id, email="rina@example.com", role="reviewer")
    await sign_in(client, reviewer.email, organization.id)
    assert (await client.get("/api/v1/agent/status")).status_code == 200
    assert (await client.post("/api/v1/agent/pause")).status_code == 403


async def test_paused_bot_answers_once_and_carries_on_after_resume(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await _joined(chat, db, organization)
    await chat.say("mulai")
    await chat.share_location()  # now at 2/5
    await sign_in(chat.client, user.email, organization.id)
    await _set(chat.client, "pause")

    assert await chat.say("Pak Slamet") == [copy.AGENT_PAUSED]
    assert await chat.say("halo?") == []  # once per pause
    conversation = await _conversation(db)
    assert conversation.step == "farmer_name"  # the engine did not move on
    stored = select(func.count()).where(Message.direction == "in", Message.body == "halo?")
    assert await db.scalar(stored) == 1  # still kept

    await _set(chat.client, "resume")
    (question,) = await chat.say("Pak Slamet")
    assert "3/5" in question

    await _set(chat.client, "pause")  # a new pause tells the worker again
    assert await chat.say("1,5") == [copy.AGENT_PAUSED]


async def test_reminders_wait_while_paused(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User, bot: FakeTelegram
) -> None:
    await _joined(chat, db, organization)
    await chat.say("mulai")
    await sign_in(chat.client, user.email, organization.id)
    await _set(chat.client, "pause")
    conversation = await _conversation(db)
    conversation.last_inbound_at = now_utc() - timedelta(hours=25)
    conversation.next_reminder_at = now_utc() - timedelta(minutes=1)
    await db.flush()
    before = len(bot.sent)
    await jobs.send_draft_reminders_job()
    assert len(bot.sent) == before
    conversation = await _conversation(db)
    assert conversation.next_reminder_at is not None
    assert conversation.next_reminder_at - now_utc() > timedelta(minutes=55)
    assert conversation.state.get("reminders_sent", 0) == 0


async def test_a_taken_over_chat_stays_quiet_while_paused(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await _joined(chat, db, organization)
    await chat.say("mulai")
    await sign_in(chat.client, user.email, organization.id)
    conversation = await _conversation(db)
    taken = await chat.client.post(f"/api/v1/conversations/{conversation.id}/takeover")
    assert taken.status_code == 200
    await _set(chat.client, "pause")
    assert await chat.say("halo admin") == []
