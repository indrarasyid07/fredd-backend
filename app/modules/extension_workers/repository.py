import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extension_workers.models import ChatContext, ExtensionWorker, FormAssignment


async def get_by_telegram_user(
    db: AsyncSession, workspace_id: uuid.UUID, telegram_user_id: str
) -> ExtensionWorker | None:
    return await db.scalar(
        select(ExtensionWorker).where(
            ExtensionWorker.workspace_id == workspace_id,
            ExtensionWorker.telegram_user_id == telegram_user_id,
        )
    )


async def get_pending_by_telegram_user(
    db: AsyncSession, telegram_user_id: str
) -> ExtensionWorker | None:
    """Any organization where this person waits for approval (oldest first)."""
    return await db.scalar(
        select(ExtensionWorker)
        .where(
            ExtensionWorker.telegram_user_id == telegram_user_id,
            ExtensionWorker.status == "pending_approval",
        )
        .order_by(ExtensionWorker.created_at)
        .limit(1)
    )


async def get_assignment(
    db: AsyncSession, extension_worker_id: uuid.UUID, form_id: uuid.UUID
) -> FormAssignment | None:
    return await db.scalar(
        select(FormAssignment).where(
            FormAssignment.extension_worker_id == extension_worker_id,
            FormAssignment.form_id == form_id,
        )
    )


async def get_assignment_by_id(db: AsyncSession, assignment_id: uuid.UUID) -> FormAssignment | None:
    return await db.get(FormAssignment, assignment_id)


async def count_active_assignments(db: AsyncSession, extension_worker_id: uuid.UUID) -> int:
    rows = await db.scalars(
        select(FormAssignment.id).where(
            FormAssignment.extension_worker_id == extension_worker_id,
            FormAssignment.status == "active",
        )
    )
    return len(list(rows))


async def get_chat_context(
    db: AsyncSession, channel_id: uuid.UUID, chat_id: str
) -> ChatContext | None:
    return await db.scalar(
        select(ChatContext).where(
            ChatContext.channel_id == channel_id, ChatContext.chat_id == chat_id
        )
    )


async def set_chat_context(
    db: AsyncSession, channel_id: uuid.UUID, chat_id: str, assignment_id: uuid.UUID | None
) -> None:
    await db.execute(
        insert(ChatContext)
        .values(channel_id=channel_id, chat_id=chat_id, active_assignment_id=assignment_id)
        .on_conflict_do_update(
            index_elements=["channel_id", "chat_id"],
            set_={"active_assignment_id": assignment_id},
        )
    )
