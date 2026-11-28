"""An admin answers instead of Fluctuz, then hands the chat back (roadmap 6.4)."""

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.auth.models import User
from app.modules.conversations import jobs, service
from app.modules.conversations.engine import copy
from app.modules.conversations.models import Conversation, Message
from app.modules.workspaces.models import Workspace
from tests.api.webhooks.test_telegram_report_flow import Worker, _joined
from tests.conftest import add_member, sign_in
from tests.telegram_fixtures import FakeTelegram


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> Worker:
    return Worker(client, bot)


async def _stuck(chat: Worker, db: AsyncSession, organization: Workspace) -> str:
    """A chat waiting for help on the area question (3/5); returns its conversation id."""
    await _joined(chat, db, organization)
    await chat.say("mulai")
    await chat.share_location()
    await chat.say("Pak Slamet")
    for text in ("banyak", "banyak", "luas sekali"):
        await chat.say(text)
    await chat.tap("help")
    conversation_id = await db.scalar(select(Conversation.id))
    return str(conversation_id)


async def _post(client: AsyncClient, url: str, json: Any = None) -> Any:
    return await client.post(url, json=json)


async def _events(client: AsyncClient) -> list[str]:
    body = (await client.get("/api/v1/activity")).json()
    return [e["type"] for e in body["data"]]


async def test_take_over_reply_and_hand_back(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User, bot: FakeTelegram
) -> None:
    cid = await _stuck(chat, db, organization)
    await sign_in(chat.client, user.email, organization.id)

    taken = await _post(chat.client, f"/api/v1/conversations/{cid}/takeover")
    assert taken.status_code == 200, taken.text
    data = taken.json()["data"]
    assert data["status"] == "taken_over" and data["taken_over_by"]["name"] == user.name
    assert data["help"] is not None  # why it came to the admin stays visible
    assert data["whatsapp_window_expires_at"] is None  # Telegram has no 24-hour window

    # The worker writes: stored and shown, the bot stays quiet.
    assert await chat.say("halo, ada orang?") == []
    before = len(bot.sent)
    sent = await _post(
        chat.client,
        f"/api/v1/conversations/{cid}/messages",
        {"text": "Luasnya kira-kira berapa ha, Pak?"},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["data"]["admin_name"] == user.name
    assert [o.text for _, o in bot.sent[before:]] == ["Luasnya kira-kira berapa ha, Pak?"]
    detail = (await chat.client.get(f"/api/v1/conversations/{cid}")).json()["data"]
    bodies = [m["body"] for m in detail["messages"]]
    assert "halo, ada orang?" in bodies and bodies[-1] == "Luasnya kira-kira berapa ha, Pak?"

    before = len(bot.sent)
    released = await _post(chat.client, f"/api/v1/conversations/{cid}/release")
    assert released.status_code == 200, released.text
    assert released.json()["data"]["status"] == "asking"
    assert released.json()["data"]["taken_over_by"] is None
    back, question = [o.text for _, o in bot.sent[before:]]
    assert back == copy.BACK_FROM_ADMIN and "3/5" in question
    (q4,) = await chat.say("1,5")  # Fluctuz carries on, attempts reset
    assert "4/5" in q4
    assert await _events(chat.client) == ["released", "taken_over", "needs_help"]


async def test_second_admin_gets_409_and_cannot_write(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User
) -> None:
    cid = await _stuck(chat, db, organization)
    other = await add_member(db, organization.id, email="rudi@example.com", role="admin")
    await sign_in(chat.client, user.email, organization.id)
    assert (await _post(chat.client, f"/api/v1/conversations/{cid}/takeover")).status_code == 200
    # Taking it over again yourself is harmless.
    assert (await _post(chat.client, f"/api/v1/conversations/{cid}/takeover")).status_code == 200

    await sign_in(chat.client, other.email, organization.id)
    second = await _post(chat.client, f"/api/v1/conversations/{cid}/takeover")
    assert second.status_code == 409
    error = second.json()["errors"][0]
    assert error["code"] == "conversation_taken_over" and user.name in second.json()["message"]
    reply = await _post(chat.client, f"/api/v1/conversations/{cid}/messages", {"text": "Halo"})
    assert reply.status_code == 403
    assert reply.json()["errors"][0]["code"] == "not_taken_over_by_you"


async def test_reviewer_and_other_workspace_are_refused(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    cid = await _stuck(chat, db, organization)
    reviewer = await add_member(db, organization.id, email="rina@example.com", role="reviewer")
    await sign_in(chat.client, reviewer.email, organization.id)
    refused = await _post(chat.client, f"/api/v1/conversations/{cid}/takeover")
    assert refused.status_code == 403 and refused.json()["errors"][0]["code"] == "forbidden"

    other = Workspace(name="Dinas Pertanian Garut", type="organization")
    db.add(other)
    await db.flush()
    stranger = await add_member(db, other.id, email="ujang@example.com", role="admin")
    await sign_in(chat.client, stranger.email, other.id)
    for action in ("takeover", "release"):
        response = await _post(chat.client, f"/api/v1/conversations/{cid}/{action}")
        assert response.status_code == 404
        assert response.json()["errors"][0]["code"] == "conversation_not_found"


async def test_release_needs_a_takeover(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User
) -> None:
    cid = await _stuck(chat, db, organization)
    await sign_in(chat.client, user.email, organization.id)
    response = await _post(chat.client, f"/api/v1/conversations/{cid}/release")
    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "conversation_not_taken_over"


async def test_idle_takeover_comes_back_after_four_hours(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User, bot: FakeTelegram
) -> None:
    cid = await _stuck(chat, db, organization)
    await sign_in(chat.client, user.email, organization.id)
    await _post(chat.client, f"/api/v1/conversations/{cid}/takeover")

    await jobs.release_stale_takeovers_job()  # too early: nothing happens
    conversation = await db.get(Conversation, cid, populate_existing=True)
    assert conversation is not None and conversation.status == "taken_over"

    await db.execute(
        update(Conversation).values(taken_over_at=now_utc() - timedelta(hours=4, minutes=1))
    )
    await db.flush()
    before = len(bot.sent)
    await jobs.release_stale_takeovers_job()
    conversation = await db.get(Conversation, cid, populate_existing=True)
    assert conversation is not None
    assert (conversation.status, conversation.taken_over_by_user_id) == ("asking", None)
    assert [o.text for _, o in bot.sent[before:]][0] == copy.BACK_FROM_ADMIN
    events = (await chat.client.get("/api/v1/activity")).json()["data"]
    assert events[0]["type"] == "auto_released" and events[0]["details"]["admin_name"] == user.name


async def test_admin_reply_keeps_the_takeover(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User
) -> None:
    cid = await _stuck(chat, db, organization)
    await sign_in(chat.client, user.email, organization.id)
    await _post(chat.client, f"/api/v1/conversations/{cid}/takeover")
    await db.execute(update(Conversation).values(taken_over_at=now_utc() - timedelta(hours=5)))
    await db.flush()
    await _post(chat.client, f"/api/v1/conversations/{cid}/messages", {"text": "Sebentar ya"})
    await jobs.release_stale_takeovers_job()
    conversation = await db.get(Conversation, cid, populate_existing=True)
    assert conversation is not None and conversation.status == "taken_over"


async def test_bot_reply_written_before_a_takeover_is_not_sent(
    chat: Worker, db: AsyncSession, organization: Workspace, bot: FakeTelegram
) -> None:
    cid = await _stuck(chat, db, organization)
    conversation = await db.get(Conversation, cid)
    assert conversation is not None
    pending = Message(
        workspace_id=conversation.workspace_id,
        conversation_id=conversation.id,
        channel_id=conversation.channel_id,
        chat_id=conversation.chat_id,
        direction="out",
        kind="text",
        body="balasan bot yang terlambat",
        payload={},
        delivery_status="pending",
    )
    db.add(pending)
    conversation.status = "taken_over"
    await db.flush()
    before = len(bot.sent)
    await service.deliver(db, bot, pending.id)
    assert len(bot.sent) == before
    assert pending.delivery_status == "failed"
