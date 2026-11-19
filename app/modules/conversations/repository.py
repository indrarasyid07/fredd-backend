import uuid
from datetime import datetime

from sqlalchemy import BigInteger, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversations.models import Message
from app.modules.extension_workers.models import ChatContext, ExtensionWorker


async def insert_inbound(db: AsyncSession, values: dict[str, object]) -> bool:
    """Store one inbound update; False when this update was stored before (webhook retry)."""
    result = await db.execute(
        insert(Message)
        .values(direction="in", **values)
        .on_conflict_do_nothing(index_elements=["channel_id", "direction", "external_id"])
        .returning(Message.id)
    )
    return result.scalar_one_or_none() is not None


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


async def get_chat_context(
    db: AsyncSession, channel_id: uuid.UUID, chat_id: str
) -> ChatContext | None:
    return await db.scalar(
        select(ChatContext).where(
            ChatContext.channel_id == channel_id, ChatContext.chat_id == chat_id
        )
    )


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
