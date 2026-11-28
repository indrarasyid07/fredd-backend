"""Retention and bot health checks (roadmap 7.4)."""

import datetime as dt
import json
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis
from app.core.time import now_utc
from app.modules.conversations import health, retention
from app.modules.conversations.models import Message
from app.modules.reports.models import Report, ReportPhoto
from app.modules.workspaces.models import Workspace
from tests.api.webhooks.test_telegram_report_flow import Worker, _answer_everything, _joined
from tests.conftest import MemoryStorage
from tests.telegram_fixtures import FakeTelegram


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> Worker:
    return Worker(client, bot)


async def _count(db: AsyncSession, model: type) -> int:
    return await db.scalar(select(func.count()).select_from(model)) or 0


async def _reported(chat: Worker, db: AsyncSession, organization: Workspace) -> ReportPhoto:
    await _joined(chat, db, organization)
    await _answer_everything(chat)
    await chat.tap("submit")
    photo = await db.scalar(select(ReportPhoto))
    assert photo is not None
    return photo


async def test_old_messages_go_but_report_photos_keep_their_file(
    chat: Worker, db: AsyncSession, organization: Workspace, media_store: MemoryStorage
) -> None:
    photo = await _reported(chat, db, organization)
    photo.object_key = "workspaces/x/messages/photo.jpg"
    media_store.objects[photo.object_key] = (b"jpg", "image/jpeg")
    media_store.objects["workspaces/x/messages/other.jpg"] = (b"jpg", "image/jpeg")
    await db.execute(update(Message).values(created_at=now_utc() - timedelta(days=400)))
    photo_message = await db.scalar(select(Message).where(Message.kind == "photo"))
    assert photo_message is not None
    photo_message.media_key = photo.object_key
    other = await db.scalar(select(Message).where(Message.kind == "text"))
    assert other is not None
    other.media_key = "workspaces/x/messages/other.jpg"
    await db.flush()
    chat_messages = await _count(db, Message)

    deleted = await retention.apply(db)
    assert deleted["messages"] == chat_messages and deleted["photos"] == 0
    assert await _count(db, Message) == 0
    assert photo.object_key in media_store.objects  # still a report photo
    assert "workspaces/x/messages/other.jpg" not in media_store.objects
    assert await _count(db, Report) == 1


async def test_photos_past_their_retention_go_and_the_report_stays(
    chat: Worker, db: AsyncSession, organization: Workspace, media_store: MemoryStorage
) -> None:
    photo = await _reported(chat, db, organization)
    photo.object_key = "workspaces/x/messages/photo.jpg"
    media_store.objects[photo.object_key] = (b"jpg", "image/jpeg")
    await db.execute(update(Report).values(received_at=now_utc() - timedelta(days=30 * 25)))
    await db.flush()
    deleted = await retention.apply(db)
    assert deleted["photos"] == 1
    assert await _count(db, ReportPhoto) == 0 and await _count(db, Report) == 1
    assert photo.object_key not in media_store.objects


async def test_a_workspace_can_keep_messages_shorter(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    await _joined(chat, db, organization)
    await chat.say("mulai")
    organization.settings = {"retention": {"messages_months": 1}}
    await db.execute(update(Message).values(created_at=now_utc() - timedelta(days=40)))
    await db.flush()
    await retention.apply(db)
    assert await db.scalar(select(func.count()).where(Message.workspace_id == organization.id)) == 0


def test_retention_setting_falls_back_to_the_default() -> None:
    assert retention.months({}, "photos_months", 24) == 24
    assert retention.months({"retention": {"photos_months": 0}}, "photos_months", 24) == 24
    assert retention.months({"retention": {"photos_months": 36}}, "photos_months", 24) == 36


def _snapshot(**changes: object) -> dict[str, object]:
    base: dict[str, object] = {
        "webhook": {"url_set": True, "pending_update_count": 0, "last_error_date": None,
                    "last_error_message": None},
        "outgoing": {"pending": 0, "oldest_pending_seconds": None, "failed_last_hour": 0,
                     "retrying": 0},
        "worker_heartbeat_seconds": 30.0,
    }  # fmt: skip
    base.update(changes)
    return base


def test_health_problems() -> None:
    now = now_utc()
    assert health.problems(_snapshot(), now) == []
    stuck = _snapshot(
        webhook={"url_set": False, "pending_update_count": 500,
                 "last_error_date": int((now - timedelta(minutes=2)).timestamp()),
                 "last_error_message": "Wrong response from the webhook: 502 Bad Gateway"},
        outgoing={"pending": 3, "oldest_pending_seconds": 900.0, "failed_last_hour": 80,
                  "retrying": 4},
        worker_heartbeat_seconds=None,
    )  # fmt: skip
    found = health.problems(stuck, now)
    assert len(found) == 6
    assert any("502 Bad Gateway" in p for p in found)
    old_error = _snapshot(webhook={"url_set": True, "pending_update_count": 0,
                                   "last_error_date": int((now - timedelta(hours=2)).timestamp()),
                                   "last_error_message": "old"})  # fmt: skip
    assert health.problems(old_error, now) == []


async def test_health_check_stores_a_snapshot(db: AsyncSession) -> None:
    await redis.set(health.HEARTBEAT_KEY, dt.datetime.now(dt.UTC).isoformat())
    snapshot = await health.check_and_alert(db)
    assert snapshot["webhook"] is None  # no bot token in tests
    assert snapshot["problems"] == []
    raw = await redis.get(health.SNAPSHOT_KEY)
    assert raw is not None
    stored = json.loads(raw)
    assert stored["outgoing"]["pending"] == 0
