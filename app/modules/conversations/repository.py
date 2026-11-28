import uuid
from datetime import datetime

from sqlalchemy import BigInteger, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.channels.models import Channel
from app.modules.conversations.models import Conversation, Message
from app.modules.extension_workers.models import ExtensionWorker, FormAssignment
from app.modules.forms.models import Form
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


async def get_timezone_name(db: AsyncSession, workspace_id: uuid.UUID) -> str:
    return await db.scalar(select(Workspace.timezone).where(Workspace.id == workspace_id)) or (
        "Asia/Jakarta"
    )


ConversationRow = tuple[Conversation, str, str, str]  # conversation, worker, form, channel type


def _conversation_rows():  # noqa: ANN202 - a Select with four columns
    return (
        select(Conversation, ExtensionWorker.name, Form.name, Channel.type)
        .join(ExtensionWorker, ExtensionWorker.id == Conversation.extension_worker_id)
        .join(Form, Form.id == Conversation.form_id)
        .join(Channel, Channel.id == Conversation.channel_id)
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
    return [(r[0], r[1], r[2], r[3]) for r in rows.all()]


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
    return (row[0], row[1], row[2], row[3]) if row else None


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
