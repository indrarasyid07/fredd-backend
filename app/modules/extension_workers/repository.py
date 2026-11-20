import uuid
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extension_workers.models import ChatContext, ExtensionWorker, FormAssignment
from app.modules.forms.models import Form
from app.modules.join_codes.models import JoinCode


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


async def get_worker(
    db: AsyncSession, workspace_id: uuid.UUID, worker_id: uuid.UUID
) -> ExtensionWorker | None:
    return await db.scalar(
        select(ExtensionWorker).where(
            ExtensionWorker.workspace_id == workspace_id, ExtensionWorker.id == worker_id
        )
    )


async def list_workers(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    status: str | None,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[ExtensionWorker]:
    """Newest first; one extra row tells the caller there is a next page."""
    stmt = select(ExtensionWorker).where(ExtensionWorker.workspace_id == workspace_id)
    if status is not None:
        stmt = stmt.where(ExtensionWorker.status == status)
    if after is not None:
        created, last_id = after
        stmt = stmt.where(
            or_(
                ExtensionWorker.created_at < created,
                and_(ExtensionWorker.created_at == created, ExtensionWorker.id < last_id),
            )
        )
    rows = await db.scalars(
        stmt.order_by(ExtensionWorker.created_at.desc(), ExtensionWorker.id.desc()).limit(limit + 1)
    )
    return list(rows)


TopicRow = tuple[uuid.UUID, uuid.UUID, str, str | None]  # worker, form, form name, code


async def list_latest_topics(
    db: AsyncSession, workspace_id: uuid.UUID, worker_ids: list[uuid.UUID]
) -> list[TopicRow]:
    """Each worker's most recent active topic with the code they joined by."""
    if not worker_ids:
        return []
    rows = await db.execute(
        select(FormAssignment.extension_worker_id, Form.id, Form.name, JoinCode.code)
        .join(Form, Form.id == FormAssignment.form_id)
        .outerjoin(JoinCode, JoinCode.id == FormAssignment.joined_via_code_id)
        .where(
            FormAssignment.workspace_id == workspace_id,
            FormAssignment.extension_worker_id.in_(worker_ids),
            FormAssignment.status == "active",
        )
        .order_by(FormAssignment.extension_worker_id, FormAssignment.updated_at.desc())
        .ext(distinct_on(FormAssignment.extension_worker_id))
    )
    return [(r[0], r[1], r[2], r[3]) for r in rows.all()]


async def list_active_assignments(
    db: AsyncSession, extension_worker_id: uuid.UUID
) -> list[FormAssignment]:
    """Most recently changed first."""
    rows = await db.scalars(
        select(FormAssignment)
        .where(
            FormAssignment.extension_worker_id == extension_worker_id,
            FormAssignment.status == "active",
        )
        .order_by(FormAssignment.updated_at.desc(), FormAssignment.id.desc())
    )
    return list(rows)
