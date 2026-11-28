"""Draft reminders (roadmap 7.1, conversation-engine.md "Draf dan pengingat").

A worker who stops in the middle of a report hears from Fluctuz 24 hours after their last
message, never inside the organization's quiet hours. At most `MAX_REMINDERS` per draft (a new
message from the worker starts the count again); a draft still untouched `ARCHIVE_AFTER` after
the worker's last message is archived: its answers go, the conversation is empty again, and the
activity log says so. Workers who are unreachable, left or blocked get nothing.
"""

import datetime as dt
import logging
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.activity import service as activity
from app.modules.channels.models import Channel
from app.modules.conversations import repository
from app.modules.conversations.engine import copy
from app.modules.conversations.engine.types import ConversationState
from app.modules.conversations.models import Conversation, Message
from app.modules.extension_workers import service as workers
from app.modules.extension_workers.models import ExtensionWorker
from app.modules.forms.models import Form

logger = logging.getLogger(__name__)

# Decided 28 Nov 2026 with the product owner.
FIRST_REMINDER_AFTER = dt.timedelta(hours=24)
MAX_REMINDERS = 2
ARCHIVE_AFTER = dt.timedelta(days=7)
DRAFT_STATUSES = ("asking", "confirming_summary")
RESUME, RESTART = "resume", "restart:yes"  # the draft buttons of reporting.py
BATCH = 200


def _clock(value: str) -> dt.time:
    hours, minutes = value.split(":")
    return dt.time(int(hours), int(minutes))


def outside_quiet_hours(
    at: dt.datetime, timezone: str, quiet: dict[str, Any] | None
) -> dt.datetime:
    """`at`, or the end of the quiet hours it falls in (in the workspace's timezone). Quiet hours
    may cross midnight (22:00–06:00)."""
    if not quiet:
        return at
    tz = ZoneInfo(timezone)
    local = at.astimezone(tz)
    start, end = _clock(quiet["start"]), _clock(quiet["end"])
    now = local.time()
    if start < end:
        inside = start <= now < end
        end_day = local.date()
    else:  # crosses midnight
        inside = now >= start or now < end
        end_day = local.date() + dt.timedelta(days=1) if now >= start else local.date()
    if not inside:
        return at
    return dt.datetime.combine(end_day, end, tzinfo=tz).astimezone(dt.UTC)


async def schedule(db: AsyncSession, conversation: Conversation, last_inbound: dt.datetime) -> None:
    """After the worker wrote: a draft gets its first reminder (count reset); anything else none."""
    state = dict(conversation.state or {})
    if conversation.status not in DRAFT_STATUSES:
        conversation.next_reminder_at = None
        return
    timezone, quiet = await repository.get_reminder_settings(db, conversation.workspace_id)
    conversation.next_reminder_at = outside_quiet_hours(
        last_inbound + FIRST_REMINDER_AFTER, timezone, quiet
    )
    if state.get("reminders_sent"):
        state["reminders_sent"] = 0
        conversation.state = state


async def send_due(db: AsyncSession) -> list[uuid.UUID]:
    """Cron: send the reminders that are due, archive the drafts left too long; returns the
    outbound rows to deliver."""
    now = now_utc()
    to_send: list[uuid.UUID] = []
    for conversation in await repository.list_due_reminders(db, now, BATCH):
        worker = await db.get(ExtensionWorker, conversation.extension_worker_id)
        last = conversation.last_inbound_at or conversation.updated_at
        if (
            worker is None
            or worker.status != "active"
            or conversation.status not in DRAFT_STATUSES
            or conversation.taken_over_by_user_id is not None
        ):
            conversation.next_reminder_at = None
            continue
        state = ConversationState.from_json(conversation.state)
        if now >= last + ARCHIVE_AFTER:
            await _archive(db, conversation, state)
            continue
        active = await workers.active_assignment(db, conversation.channel_id, conversation.chat_id)
        if (
            state.reminders_sent >= MAX_REMINDERS
            or active is None
            or active.form_id != conversation.form_id
        ):
            # Done reminding (or another topic is open in the chat): only the archive is left.
            conversation.next_reminder_at = last + ARCHIVE_AFTER
            continue
        to_send.append(await _remind(db, conversation, state, worker))
        state.reminders_sent += 1
        conversation.state = state.to_json()
        if state.reminders_sent >= MAX_REMINDERS:
            conversation.next_reminder_at = last + ARCHIVE_AFTER
        else:
            timezone, quiet = await repository.get_reminder_settings(db, conversation.workspace_id)
            conversation.next_reminder_at = outside_quiet_hours(
                now + FIRST_REMINDER_AFTER, timezone, quiet
            )
    await db.commit()
    return to_send


async def _remind(
    db: AsyncSession, conversation: Conversation, state: ConversationState, worker: ExtensionWorker
) -> uuid.UUID:
    form = await db.get(Form, conversation.form_id)
    text = copy.draft_reminder(
        worker.name.split()[0] if worker.name else "", form.name if form else ""
    )
    message = Message(
        workspace_id=conversation.workspace_id,
        conversation_id=conversation.id,
        channel_id=conversation.channel_id,
        chat_id=conversation.chat_id,
        direction="out",
        kind="text",
        body=text,
        payload={
            "buttons": [
                {"label": copy.RESUME, "value": RESUME},
                {"label": copy.RESTART, "value": RESTART},
            ],
            "ask_location": False,
            "reminder": state.reminders_sent + 1,
        },
        delivery_status="pending",
    )
    db.add(message)
    await db.flush()
    await _event(db, conversation, "reminder_sent", form, reminder=state.reminders_sent + 1)
    return message.id


async def _archive(db: AsyncSession, conversation: Conversation, state: ConversationState) -> None:
    answered = len([v for v in state.answers.values() if v is not None])
    fresh = ConversationState(topic_id=state.topic_id)
    conversation.state = fresh.to_json()
    conversation.status, conversation.step, conversation.failed_attempts = fresh.status, None, 0
    conversation.next_reminder_at = None
    form = await db.get(Form, conversation.form_id)
    await _event(db, conversation, "draft_archived", form, answered=answered)
    logger.info("draft of conversation %s archived", conversation.id)


async def _event(
    db: AsyncSession, conversation: Conversation, type: str, form: Form | None, **details: int
) -> None:
    channel = await db.get(Channel, conversation.channel_id)
    await activity.record(
        db,
        workspace_id=conversation.workspace_id,
        type=type,
        status="done",
        channel=channel.type if channel else None,
        extension_worker_id=conversation.extension_worker_id,
        conversation_id=conversation.id,
        details={"form_name": form.name if form else "", **details},
    )
