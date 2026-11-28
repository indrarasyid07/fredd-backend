import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import BigInteger, func, select, update
from sqlalchemy import delete as sa_delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activity.models import ActivityEvent
from app.modules.auth.models import User
from app.modules.channels.models import Channel
from app.modules.conversations.models import Conversation, Message
from app.modules.extension_workers.models import ChatContext, ExtensionWorker, FormAssignment
from app.modules.forms.models import Form
from app.modules.reports.models import Report
from app.modules.workspaces.models import Workspace


async def insert_inbound(db: AsyncSession, values: dict[str, object]) -> bool:
    """Store one inbound update; False when this update was stored before (webhook retry)."""
    result = await db.execute(
        insert(Message)
        .values(direction="in", **values)
        .on_conflict_do_nothing(index_elements=["channel_id", "direction", "external_id"])
        .returning(Message.id)
    )
    return result.scalar_one_or_none() is not None


async def album_age(db: AsyncSession, channel_id: uuid.UUID, chat_id: str) -> float | None:
    """Seconds since the newest unprocessed album photo of a chat arrived; None when there is
    none. Database clock on both sides, so app and database clocks need not agree."""
    newest = func.max(Message.created_at)
    age = await db.scalar(
        select(func.extract("epoch", func.clock_timestamp() - newest)).where(
            Message.channel_id == channel_id,
            Message.chat_id == chat_id,
            Message.direction == "in",
            Message.processed_at.is_(None),
            Message.payload.has_key("media_group_id"),
        )
    )
    return float(age) if age is not None else None


async def list_unprocessed(db: AsyncSession, channel_id: uuid.UUID, chat_id: str) -> list[Message]:
    """Oldest first. Telegram dates have one-second precision, so the update id (the order
    Telegram received them) breaks ties (3.5c)."""
    rows = await db.scalars(
        select(Message)
        .where(
            Message.channel_id == channel_id,
            Message.chat_id == chat_id,
            Message.direction == "in",
            Message.processed_at.is_(None),
        )
        .order_by(
            Message.channel_sent_at,
            Message.payload["update_id"].astext.cast(BigInteger),
            Message.created_at,
            Message.id,
        )
        .with_for_update(skip_locked=True)
    )
    return list(rows)


async def has_unprocessed(db: AsyncSession, channel_id: uuid.UUID, chat_id: str) -> bool:
    found = await db.scalar(
        select(Message.id)
        .where(
            Message.channel_id == channel_id,
            Message.chat_id == chat_id,
            Message.direction == "in",
            Message.processed_at.is_(None),
        )
        .limit(1)
    )
    return found is not None


async def mark_unreachable(db: AsyncSession, telegram_user_id: str, at: datetime) -> int:
    """The person blocked the bot: in every organization they joined (B-048 status)."""
    result = await db.execute(
        update(ExtensionWorker)
        .where(
            ExtensionWorker.telegram_user_id == telegram_user_id,
            ExtensionWorker.status == "active",
        )
        .values(status="unreachable", updated_at=at)
    )
    return result.rowcount  # type: ignore[attr-defined]


async def get_conversation(
    db: AsyncSession, extension_worker_id: uuid.UUID, form_id: uuid.UUID
) -> Conversation | None:
    return await db.scalar(
        select(Conversation).where(
            Conversation.extension_worker_id == extension_worker_id,
            Conversation.form_id == form_id,
        )
    )


async def list_chat_messages(
    db: AsyncSession, channel_id: uuid.UUID, chat_id: str, limit: int
) -> list[Message]:
    rows = await db.scalars(
        select(Message)
        .where(Message.channel_id == channel_id, Message.chat_id == chat_id)
        # created_at is the transaction's start time, shared by every reply of one batch; the
        # UUID v7 id is monotonic in creation order and breaks the tie.
        .order_by(Message.created_at, Message.id)
        .limit(limit)
    )
    return list(rows)


TopicRow = tuple[FormAssignment, str, str]  # assignment, organization name, form name


async def list_chat_topics(db: AsyncSession, telegram_user_id: str) -> list[TopicRow]:
    """Every active topic of this chat identity, in any organization, oldest first."""
    rows = await db.execute(
        select(FormAssignment, Workspace.name, Form.name)
        .join(ExtensionWorker, ExtensionWorker.id == FormAssignment.extension_worker_id)
        .join(Workspace, Workspace.id == FormAssignment.workspace_id)
        .join(Form, Form.id == FormAssignment.form_id)
        .where(
            ExtensionWorker.telegram_user_id == telegram_user_id,
            ExtensionWorker.status == "active",
            FormAssignment.status == "active",
        )
        .order_by(FormAssignment.created_at, FormAssignment.id)
    )
    return [(r[0], r[1], r[2]) for r in rows.all()]


async def get_reminder_settings(
    db: AsyncSession, workspace_id: uuid.UUID
) -> tuple[str, dict[str, object] | None]:
    """The workspace's timezone and quiet hours ({start, end}, or null)."""
    row = (
        await db.execute(
            select(Workspace.timezone, Workspace.quiet_hours).where(Workspace.id == workspace_id)
        )
    ).first()
    return (row[0] or "Asia/Jakarta", row[1]) if row else ("Asia/Jakarta", None)


async def list_due_reminders(db: AsyncSession, now: datetime, limit: int) -> list[Conversation]:
    """Every workspace (a cron job); rows locked so two runs never remind twice."""
    rows = await db.scalars(
        select(Conversation)
        .where(Conversation.next_reminder_at.is_not(None), Conversation.next_reminder_at <= now)
        .order_by(Conversation.next_reminder_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(rows)


async def get_timezone_name(db: AsyncSession, workspace_id: uuid.UUID) -> str:
    return await db.scalar(select(Workspace.timezone).where(Workspace.id == workspace_id)) or (
        "Asia/Jakarta"
    )


# conversation, worker, form, channel type, name of the admin who took it over
ConversationRow = tuple[Conversation, str, str, str, str | None]


def _conversation_rows():  # noqa: ANN202 - a Select with five columns
    return (
        select(Conversation, ExtensionWorker.name, Form.name, Channel.type, User.name)
        .join(ExtensionWorker, ExtensionWorker.id == Conversation.extension_worker_id)
        .join(Form, Form.id == Conversation.form_id)
        .join(Channel, Channel.id == Conversation.channel_id)
        .outerjoin(User, User.id == Conversation.taken_over_by_user_id)
    )


async def list_conversations(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    status: str | None,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[ConversationRow]:
    """Most recently changed first."""
    stmt = _conversation_rows().where(Conversation.workspace_id == workspace_id)
    if status is not None:
        stmt = stmt.where(Conversation.status == status)
    if after is not None:
        changed, last_id = after
        stmt = stmt.where(
            (Conversation.updated_at < changed)
            | ((Conversation.updated_at == changed) & (Conversation.id < last_id))
        )
    rows = await db.execute(
        stmt.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit + 1)
    )
    return [(r[0], r[1], r[2], r[3], r[4]) for r in rows.all()]


async def get_conversation_row(
    db: AsyncSession, workspace_id: uuid.UUID, conversation_id: uuid.UUID
) -> ConversationRow | None:
    row = (
        await db.execute(
            _conversation_rows().where(
                Conversation.workspace_id == workspace_id, Conversation.id == conversation_id
            )
        )
    ).first()
    return (row[0], row[1], row[2], row[3], row[4]) if row else None


async def latest_messages(
    db: AsyncSession, workspace_id: uuid.UUID, conversation_id: uuid.UUID, limit: int
) -> list[Message]:
    """Oldest first."""
    rows = await db.scalars(
        select(Message)
        .where(Message.workspace_id == workspace_id, Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    return list(reversed(list(rows)))


async def take_over(
    db: AsyncSession, workspace_id: uuid.UUID, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    """One conditional UPDATE, so two admins cannot both win (data-model.md "Takeover")."""
    result = await db.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.workspace_id == workspace_id,
            Conversation.taken_over_by_user_id.is_(None),
        )
        .values(status="taken_over", taken_over_by_user_id=user_id, taken_over_at=func.now())
        .returning(Conversation.id)
    )
    return result.scalar_one_or_none() is not None


async def lock_conversation(
    db: AsyncSession, workspace_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation | None:
    return await db.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.workspace_id == workspace_id)
        .with_for_update()
    )


def _last_admin_reply():  # noqa: ANN202 - a scalar subquery
    return (
        select(func.max(Message.created_at))
        .where(
            Message.conversation_id == Conversation.id,
            Message.direction == "out",
            Message.payload.has_key("admin_user_id"),
        )
        .scalar_subquery()
    )


async def list_stale_takeovers(db: AsyncSession, before: datetime) -> list[Conversation]:
    """Taken over, and the admin wrote nothing since `before` (every workspace: a cron job)."""
    last = func.coalesce(_last_admin_reply(), Conversation.taken_over_at)
    rows = await db.scalars(
        select(Conversation)
        .where(Conversation.taken_over_by_user_id.is_not(None), last < before)
        .with_for_update(skip_locked=True)
    )
    return list(rows)


async def list_due_retries(db: AsyncSession, now: datetime, limit: int) -> list[Message]:
    """Failed sends whose retry time has come (every workspace: a cron job)."""
    rows = await db.scalars(
        select(Message)
        .where(
            Message.retry_at.is_not(None),
            Message.retry_at <= now,
            Message.direction == "out",
            Message.delivery_status == "failed",
        )
        .order_by(Message.retry_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(rows)


LogRow = tuple[Message, str, str | None, uuid.UUID | None, str | None]  # + channel, worker


def _log_rows(workspace_id: uuid.UUID):  # noqa: ANN202 - a Select with five columns
    return (
        select(
            Message,
            Channel.type,
            ExtensionWorker.name,
            ExtensionWorker.id,
            ExtensionWorker.phone_e164,
        )  # fmt: skip
        .join(Channel, Channel.id == Message.channel_id)
        .outerjoin(Conversation, Conversation.id == Message.conversation_id)
        .outerjoin(ExtensionWorker, ExtensionWorker.id == Conversation.extension_worker_id)
        .where(Message.workspace_id == workspace_id)
    )


async def get_channel_log(
    db: AsyncSession, workspace_id: uuid.UUID, message_id: uuid.UUID
) -> LogRow | None:
    row = (await db.execute(_log_rows(workspace_id).where(Message.id == message_id))).first()
    return (row[0], row[1], row[2], row[3], row[4]) if row else None


async def list_channel_logs(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    failed_only: bool,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[LogRow]:
    """Newest first. `failed_only`: outgoing sends Fluctuz gave up on ("Susul yang gagal")."""
    stmt = _log_rows(workspace_id)
    if failed_only:
        stmt = stmt.where(
            Message.direction == "out",
            Message.delivery_status.in_(("failed", "uncertain")),
            Message.retry_at.is_(None),
        )
    if after is not None:
        created, last_id = after
        stmt = stmt.where(
            (Message.created_at < created)
            | ((Message.created_at == created) & (Message.id < last_id))
        )
    rows = await db.execute(
        stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
    )
    return [(r[0], r[1], r[2], r[3], r[4]) for r in rows.all()]


async def lock_workspace_message(
    db: AsyncSession, workspace_id: uuid.UUID, message_id: uuid.UUID
) -> Message | None:
    return await db.scalar(
        select(Message)
        .where(Message.id == message_id, Message.workspace_id == workspace_id)
        .with_for_update()
    )


async def list_expired_messages(
    db: AsyncSession, workspace_id: uuid.UUID | None, before: datetime, limit: int
) -> list[tuple[uuid.UUID, str | None]]:
    """Messages past retention (7.4); `workspace_id` None = chats bound to no organization."""
    owner = (
        Message.workspace_id.is_(None)
        if workspace_id is None
        else Message.workspace_id == workspace_id
    )
    rows = await db.execute(
        select(Message.id, Message.media_key).where(owner, Message.created_at < before).limit(limit)
    )
    return [(r[0], r[1]) for r in rows.all()]


async def delete_messages(db: AsyncSession, message_ids: list[uuid.UUID]) -> None:
    await db.execute(sa_delete(Message).where(Message.id.in_(message_ids)))


async def list_workspace_settings(db: AsyncSession) -> list[tuple[uuid.UUID, dict[str, Any]]]:
    rows = await db.execute(select(Workspace.id, Workspace.settings))
    return [(r[0], r[1] or {}) for r in rows.all()]


async def outgoing_stats(db: AsyncSession, now: datetime) -> dict[str, Any]:
    """Outgoing sends for the health check (7.4): what is waiting, failing, retrying."""
    out = Message.direction == "out"
    oldest = await db.scalar(
        select(func.min(Message.created_at)).where(out, Message.delivery_status == "pending")
    )
    pending = await db.scalar(select(func.count()).where(out, Message.delivery_status == "pending"))
    failed = await db.scalar(
        select(func.count()).where(
            out,
            Message.delivery_status == "failed",
            Message.retry_at.is_(None),
            Message.created_at >= now - timedelta(hours=1),
        )
    )
    retrying = await db.scalar(select(func.count()).where(Message.retry_at.is_not(None)))
    return {
        "pending": pending or 0,
        "oldest_pending_seconds": (now - oldest).total_seconds() if oldest else None,
        "failed_last_hour": failed or 0,
        "retrying": retrying or 0,
    }


# --- Moving an extension worker to a new identity (roadmap 7.5) ---------------------------------


async def lock_worker(
    db: AsyncSession, workspace_id: uuid.UUID, worker_id: uuid.UUID
) -> ExtensionWorker | None:
    return await db.scalar(
        select(ExtensionWorker)
        .where(ExtensionWorker.id == worker_id, ExtensionWorker.workspace_id == workspace_id)
        .with_for_update()
    )


async def worker_assignments(db: AsyncSession, worker_id: uuid.UUID) -> list[FormAssignment]:
    rows = await db.scalars(
        select(FormAssignment).where(FormAssignment.extension_worker_id == worker_id)
    )
    return list(rows)


async def repoint_chat_contexts(
    db: AsyncSession, from_assignment: uuid.UUID, to_assignment: uuid.UUID
) -> None:
    await db.execute(
        update(ChatContext)
        .where(ChatContext.active_assignment_id == from_assignment)
        .values(active_assignment_id=to_assignment)
    )


async def clear_chat_contexts(db: AsyncSession, chat_id: str, worker_id: uuid.UUID) -> None:
    """The old account's chat stops pointing at this worker's topics."""
    mine = select(FormAssignment.id).where(FormAssignment.extension_worker_id == worker_id)
    await db.execute(
        update(ChatContext)
        .where(ChatContext.chat_id == chat_id, ChatContext.active_assignment_id.in_(mine))
        .values(active_assignment_id=None)
    )


async def move_conversation_rows(
    db: AsyncSession, from_conversation: uuid.UUID, to_conversation: uuid.UUID
) -> None:
    for model in (Message, Report, ActivityEvent):
        await db.execute(
            update(model)
            .where(model.conversation_id == from_conversation)
            .values(conversation_id=to_conversation)
        )


async def move_worker_rows(db: AsyncSession, from_worker: uuid.UUID, to_worker: uuid.UUID) -> None:
    for model in (Report, ActivityEvent, Conversation, FormAssignment):
        await db.execute(
            update(model)
            .where(model.extension_worker_id == from_worker)
            .values(extension_worker_id=to_worker)
        )


async def point_conversations_to(db: AsyncSession, worker_id: uuid.UUID, chat_id: str) -> None:
    """Every conversation of the worker is now with the new account's chat."""
    await db.execute(
        update(Conversation)
        .where(Conversation.extension_worker_id == worker_id)
        .values(chat_id=chat_id)
    )
