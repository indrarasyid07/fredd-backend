"""Aturan ambil alih: IF something happens THEN hand over or alert (roadmap 6.7)."""

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.activity.models import ActivityEvent
from app.modules.auth.models import User
from app.modules.conversations import jobs
from app.modules.conversations.engine import copy
from app.modules.workspaces.models import Workspace
from tests.api.webhooks.test_telegram_report_flow import (
    Worker,
    _answer_everything,
    _conversation,
    _joined,
)
from tests.conftest import add_member, sign_in
from tests.telegram_fixtures import FakeTelegram

URL = "/api/v1/agent/rules"


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> Worker:
    return Worker(client, bot)


async def _turn_on(client: AsyncClient, rule_id: str, **changes: Any) -> None:
    rules = (await client.get(URL)).json()["data"]["rules"]
    for rule in rules:
        if rule["id"] == rule_id:
            rule.update(enabled=True, **changes)
    response = await client.put(URL, json={"rules": rules})
    assert response.status_code == 200, response.text


async def _events(db: AsyncSession, type: str) -> list[ActivityEvent]:
    return list(await db.scalars(select(ActivityEvent).where(ActivityEvent.type == type)))


async def test_suggested_rules_are_off_and_admins_save_them(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await sign_in(client, user.email, organization.id)
    data = (await client.get(URL)).json()["data"]
    assert [r["id"] for r in data["rules"]] == [
        "ask-for-person", "blurry-photos", "infected-report", "no-reply",
    ]  # fmt: skip
    assert not any(r["enabled"] for r in data["rules"]) and data["updated_at"] is None
    assert "blurry_photo" not in data["available_triggers"]

    bad = [{**data["rules"][2], "action": "handover"}]
    assert (await client.put(URL, json={"rules": bad})).status_code == 422
    twice = [data["rules"][0], data["rules"][0]]
    assert (await client.put(URL, json={"rules": twice})).status_code == 422

    await _turn_on(client, "ask-for-person")
    saved = (await client.get(URL)).json()["data"]
    assert saved["rules"][0]["enabled"] is True and saved["updated_at"] is not None

    reviewer = await add_member(db, organization.id, email="rina@example.com", role="reviewer")
    await sign_in(client, reviewer.email, organization.id)
    assert (await client.get(URL)).status_code == 200
    assert (await client.put(URL, json={"rules": []})).status_code == 403


async def test_keyword_hands_the_chat_to_an_admin(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await _joined(chat, db, organization)
    await chat.say("mulai")
    await chat.share_location()
    assert "3/5" in (await chat.say("Pak Slamet"))[0]  # rules are off: nothing happens
    await sign_in(chat.client, user.email, organization.id)
    await _turn_on(chat.client, "ask-for-person", priority="urgent")

    assert await chat.say("Saya mau bicara dengan PETUGAS, tolong.") == [copy.HELP_SENT]
    assert (await _conversation(db)).status == "needs_help"
    (item,) = (
        await chat.client.get("/api/v1/conversations", params={"status": "needs_help"})
    ).json()["data"]
    assert item["help"]["reason"] == "rule" and item["help"]["priority"] == "urgent"
    assert item["help"]["rule_name"] == "Penyuluh minta bicara dengan petugas"
    assert item["help"]["field"] == "land_area"


async def test_notify_alerts_and_the_bot_carries_on(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await sign_in(chat.client, user.email, organization.id)
    await _turn_on(chat.client, "ask-for-person", action="notify")
    await _joined(chat, db, organization)
    await chat.say("mulai")
    replies = await chat.say("admin")  # not a location, but no handover either
    assert copy.HELP_SENT not in replies
    assert (await _conversation(db)).status == "asking"
    (event,) = await _events(db, "rule_alert")
    assert event.details["rule_id"] == "ask-for-person" and event.status == "needs_review"


async def test_infected_report_raises_an_alert(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await sign_in(chat.client, user.email, organization.id)
    await _turn_on(chat.client, "infected-report")
    await _joined(chat, db, organization)
    await _answer_everything(chat)  # answers Terserang
    await chat.tap("submit")
    (event,) = await _events(db, "rule_alert")
    assert event.details["condition"] == "infected" and event.details["code"].startswith("LP-")
    assert event.details["priority"] == "urgent"


async def test_no_reply_after_the_second_reminder_hands_over(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await sign_in(chat.client, user.email, organization.id)
    await _turn_on(chat.client, "no-reply")
    await _joined(chat, db, organization)
    await chat.say("mulai")
    for hours in (25, 49):  # both reminders
        conversation = await _conversation(db)
        conversation.last_inbound_at = now_utc() - timedelta(hours=hours)
        conversation.next_reminder_at = now_utc() - timedelta(minutes=1)
        await db.flush()
        await jobs.send_draft_reminders_job()
    conversation = await _conversation(db)
    assert conversation.state["reminders_sent"] == 2
    assert conversation.next_reminder_at is not None
    assert conversation.next_reminder_at - now_utc() <= timedelta(hours=3)  # the rule's hours

    conversation.state = {
        **conversation.state,
        "reminded_at": (now_utc() - timedelta(hours=4)).isoformat(),
    }
    conversation.next_reminder_at = now_utc() - timedelta(minutes=1)
    await db.flush()
    await jobs.send_draft_reminders_job()
    conversation = await _conversation(db)
    assert conversation.status == "needs_help"
    (event,) = [e for e in await _events(db, "needs_help") if e.details.get("reason") == "rule"]
    assert event.details["rule_id"] == "no-reply"
