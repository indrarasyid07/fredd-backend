"""Aktivitas Agent log and the "Perlu bantuan admin" queue (roadmap 6.2-6.3)."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.conversations.models import Conversation
from app.modules.workspaces.models import Workspace
from tests.api.webhooks.test_telegram_report_flow import Worker, _answer_everything, _joined
from tests.conftest import add_member, sign_in
from tests.telegram_fixtures import FakeTelegram


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> Worker:
    return Worker(client, bot)


async def _stuck(chat: Worker) -> None:
    """Three unreadable areas, then "Minta bantuan admin"."""
    await chat.say("mulai")
    await chat.share_location()
    await chat.say("Pak Slamet")
    for text in ("banyak", "banyak", "luas sekali"):
        await chat.say(text)
    await chat.tap("help")


async def _get(client: AsyncClient, url: str, **params: Any) -> Any:
    response = await client.get(url, params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True and body["errors"] == []
    return body


async def test_needs_help_shows_in_the_queue_and_the_log(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await _joined(chat, db, organization)
    await _stuck(chat)
    await sign_in(chat.client, user.email, organization.id)

    (item,) = (await _get(chat.client, "/api/v1/conversations", status="needs_help"))["data"]
    assert item["status"] == "needs_help" and item["channel"] == "telegram"
    assert item["form"]["name"] == "Survei Tanaman"
    assert item["help"]["field"] == "land_area" and item["help"]["field_label"]
    assert item["help"]["reason"] in ("failed_attempts", "asked_for_help")

    (event,) = (await _get(chat.client, "/api/v1/activity"))["data"]
    assert (event["type"], event["status"]) == ("needs_help", "needs_help")
    assert event["conversation_id"] == item["id"]
    assert event["extension_worker"]["id"] == item["extension_worker"]["id"]
    assert event["details"]["form_name"] == "Survei Tanaman"

    detail = (await _get(chat.client, f"/api/v1/conversations/{item['id']}"))["data"]
    assert detail["help"] == item["help"]
    bodies = [m["body"] for m in detail["messages"]]
    assert "luas sekali" in bodies
    assert {m["direction"] for m in detail["messages"]} == {"in", "out"}


async def test_a_submitted_report_is_logged_and_leaves_no_help_item(
    chat: Worker, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await _joined(chat, db, organization)
    await _answer_everything(chat)
    await chat.tap("submit")
    await sign_in(chat.client, user.email, organization.id)

    (event,) = (await _get(chat.client, "/api/v1/activity", type="report_received"))["data"]
    assert event["status"] in ("done", "needs_review")
    assert event["details"]["code"].startswith("LP-")
    assert (await _get(chat.client, "/api/v1/activity", type="needs_help"))["data"] == []
    assert (await _get(chat.client, "/api/v1/conversations", status="needs_help"))["data"] == []
    (conversation,) = (await _get(chat.client, "/api/v1/conversations"))["data"]
    assert conversation["status"] == "submitted" and conversation["help"] is None


async def test_reviewer_reads_pages_of_the_log(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    await _joined(chat, db, organization)
    await _answer_everything(chat)
    await chat.tap("submit")
    await chat.say("mulai")  # a second report, stuck this time
    await chat.share_location()
    await chat.say("Pak Asep")
    for text in ("banyak", "banyak", "luas sekali"):
        await chat.say(text)
    await chat.tap("help")
    reviewer = await add_member(db, organization.id, email="rina@example.com", role="reviewer")
    await sign_in(chat.client, reviewer.email, organization.id)

    first = await _get(chat.client, "/api/v1/activity", limit=1)
    assert first["data"][0]["type"] == "needs_help"  # newest first
    page = first["meta"]["pagination"]
    assert page["has_more"] is True
    second = await _get(chat.client, "/api/v1/activity", limit=1, cursor=page["next_cursor"])
    assert second["data"][0]["type"] == "report_received"
    assert second["meta"]["pagination"] == {"next_cursor": None, "limit": 1, "has_more": False}


async def test_other_workspaces_see_nothing(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    await _joined(chat, db, organization)
    await _stuck(chat)
    other = Workspace(name="Dinas Pertanian Garut", type="organization")
    db.add(other)
    await db.flush()
    stranger = await add_member(db, other.id, email="ujang@example.com", role="admin")
    await sign_in(chat.client, stranger.email, other.id)

    assert (await _get(chat.client, "/api/v1/activity"))["data"] == []
    assert (await _get(chat.client, "/api/v1/conversations"))["data"] == []

    chat.client.headers["X-Workspace-Id"] = str(organization.id)
    assert (await chat.client.get("/api/v1/activity")).status_code in (403, 404)
    chat.client.headers["X-Workspace-Id"] = str(other.id)
    conversation_id = await db.scalar(select(Conversation.id))
    response = await chat.client.get(f"/api/v1/conversations/{conversation_id}")
    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "conversation_not_found"


async def test_signed_out_is_refused(client: AsyncClient) -> None:
    for url in ("/api/v1/activity", "/api/v1/conversations"):
        response = await client.get(url)
        assert response.status_code == 401
        assert response.json()["errors"][0]["code"] == "not_authenticated"
