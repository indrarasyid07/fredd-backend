"""Draft reminders, quiet hours, and archiving drafts left for 7 days (roadmap 7.1)."""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.activity.models import ActivityEvent
from app.modules.conversations import jobs, reminders
from app.modules.conversations.engine import copy
from app.modules.conversations.models import Conversation
from app.modules.extension_workers.models import ExtensionWorker
from app.modules.workspaces.models import Workspace
from tests.api.webhooks.test_telegram_report_flow import Worker, _conversation, _joined
from tests.telegram_fixtures import FakeTelegram


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> Worker:
    return Worker(client, bot)


async def _draft(chat: Worker, db: AsyncSession, organization: Workspace) -> Conversation:
    """Stopped at the farmer's name (2/5)."""
    await _joined(chat, db, organization)
    await chat.say("mulai")
    await chat.share_location()
    return await _conversation(db)


async def _due(db: AsyncSession, conversation: Conversation, *, quiet_for: timedelta) -> None:
    """The worker's last message was `quiet_for` ago and a reminder is due now."""
    conversation.last_inbound_at = now_utc() - quiet_for
    conversation.next_reminder_at = now_utc() - timedelta(minutes=1)
    await db.flush()


async def _run(bot: FakeTelegram) -> list[str]:
    before = len(bot.sent)
    await jobs.send_draft_reminders_job()
    return [out.text for _, out in bot.sent[before:]]


async def _events(db: AsyncSession, type: str) -> int:
    count = select(func.count()).select_from(ActivityEvent).where(ActivityEvent.type == type)
    return await db.scalar(count) or 0


async def test_a_draft_is_reminded_twice_then_left_alone(
    chat: Worker, db: AsyncSession, organization: Workspace, bot: FakeTelegram
) -> None:
    conversation = await _draft(chat, db, organization)
    assert conversation.next_reminder_at is not None  # scheduled when the worker stopped

    await _due(db, conversation, quiet_for=timedelta(hours=25))
    (first,) = await _run(bot)
    assert "Survei Tanaman" in first and "belum selesai" in first
    assert [b.value for b in bot.sent[-1][1].buttons] == ["resume", "restart:yes"]
    conversation = await _conversation(db)
    assert conversation.state["reminders_sent"] == 1
    assert conversation.next_reminder_at is not None
    assert conversation.next_reminder_at > now_utc() + timedelta(hours=23)

    await _due(db, conversation, quiet_for=timedelta(hours=49))
    assert len(await _run(bot)) == 1
    conversation = await _conversation(db)
    assert conversation.state["reminders_sent"] == 2
    # Only the archive is left, 7 days after the worker's last message.
    assert conversation.last_inbound_at is not None
    assert conversation.next_reminder_at == conversation.last_inbound_at + reminders.ARCHIVE_AFTER

    conversation.next_reminder_at = now_utc() - timedelta(minutes=1)
    await db.flush()
    assert await _run(bot) == []  # no third reminder
    assert await _events(db, "reminder_sent") == 2


async def test_resume_from_a_reminder_and_a_reply_resets_the_count(
    chat: Worker, db: AsyncSession, organization: Workspace, bot: FakeTelegram
) -> None:
    conversation = await _draft(chat, db, organization)
    await _due(db, conversation, quiet_for=timedelta(hours=25))
    await _run(bot)

    replies = await chat.tap("resume")
    assert any("2/5" in r for r in replies)
    conversation = await _conversation(db)
    assert conversation.state.get("reminders_sent", 0) == 0
    assert conversation.next_reminder_at is not None


async def test_quiet_hours_move_the_reminder(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    organization.quiet_hours = {"start": "00:00", "end": "23:59"}  # nearly always quiet
    await db.flush()
    conversation = await _draft(chat, db, organization)
    assert conversation.next_reminder_at is not None
    local = conversation.next_reminder_at.astimezone(reminders.ZoneInfo("Asia/Jakarta"))
    assert (local.hour, local.minute) == (23, 59)


async def test_a_submitted_report_needs_no_reminder(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    from tests.api.webhooks.test_telegram_report_flow import _answer_everything

    await _joined(chat, db, organization)
    await _answer_everything(chat)
    await chat.tap("submit")
    assert (await _conversation(db)).next_reminder_at is None


async def test_a_draft_left_for_7_days_is_archived(
    chat: Worker, db: AsyncSession, organization: Workspace, bot: FakeTelegram
) -> None:
    conversation = await _draft(chat, db, organization)
    await _due(db, conversation, quiet_for=timedelta(days=7, minutes=1))
    assert await _run(bot) == []  # archived quietly
    conversation = await _conversation(db)
    assert conversation.status == "idle" and conversation.state.get("answers") == {}
    assert conversation.next_reminder_at is None
    event = await db.scalar(select(ActivityEvent).where(ActivityEvent.type == "draft_archived"))
    assert event is not None and event.details["answered"] == 1


async def test_unreachable_worker_gets_no_reminder(
    chat: Worker, db: AsyncSession, organization: Workspace, bot: FakeTelegram
) -> None:
    conversation = await _draft(chat, db, organization)
    worker = await db.get(ExtensionWorker, conversation.extension_worker_id)
    assert worker is not None
    worker.status = "unreachable"
    await _due(db, conversation, quiet_for=timedelta(hours=25))
    assert await _run(bot) == []
    assert (await _conversation(db)).next_reminder_at is None


async def test_help_and_takeover_get_no_reminder(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    await _joined(chat, db, organization)
    await chat.say("mulai")
    await chat.share_location()
    await chat.say("Pak Slamet")
    for text in ("banyak", "banyak", "luas sekali"):
        await chat.say(text)
    await chat.tap("help")
    assert (await _conversation(db)).next_reminder_at is None
    assert copy.HELP_SENT  # waiting for an admin, not a reminder
