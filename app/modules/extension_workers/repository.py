import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extension_workers.models import ChatContext, ExtensionWorker, FormAssignment
from app.modules.forms.models import Form
from app.modules.join_codes.models import JoinCode
from app.modules.reference_data.models import ReferenceData

_EW = ExtensionWorker
# Workers who never wrote sort last under "last active".
_NEVER = datetime(1970, 1, 1, tzinfo=UTC)


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


async def get_by_phone(
    db: AsyncSession, workspace_id: uuid.UUID, phone_e164: str
) -> ExtensionWorker | None:
    return await db.scalar(
        select(ExtensionWorker).where(
            ExtensionWorker.workspace_id == workspace_id, ExtensionWorker.phone_e164 == phone_e164
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
    statuses: list[str] | None,
    channel: str | None,
    form_id: uuid.UUID | None,
    query: str | None,
    sort: str,
    after: tuple[Any, uuid.UUID] | None,
    limit: int,
) -> list[ExtensionWorker]:
    """One extra row tells the caller there is a next page. `after` is (sort key, id)."""
    stmt = select(_EW).where(_EW.workspace_id == workspace_id)
    if statuses:
        stmt = stmt.where(_EW.status.in_(statuses))
    if channel == "telegram":
        stmt = stmt.where(_EW.telegram_user_id.is_not(None))
    elif channel == "whatsapp":
        stmt = stmt.where(_EW.telegram_user_id.is_(None))
    if form_id is not None:
        stmt = stmt.where(
            select(FormAssignment.id)
            .where(
                FormAssignment.extension_worker_id == _EW.id,
                FormAssignment.form_id == form_id,
                FormAssignment.status == "active",
            )
            .exists()
        )
    if query:
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(_EW.name.ilike(pattern))
    key, descending = sort_key(sort)
    if after is not None:
        value, last_id = after
        if descending:
            stmt = stmt.where(or_(key < value, and_(key == value, _EW.id < last_id)))
        else:
            stmt = stmt.where(or_(key > value, and_(key == value, _EW.id > last_id)))
    order = (key.desc(), _EW.id.desc()) if descending else (key.asc(), _EW.id.asc())
    rows = await db.scalars(stmt.order_by(*order).limit(limit + 1))
    return list(rows)


def sort_key(sort: str) -> tuple[Any, bool]:
    """The column a list sort orders by, and whether it is descending."""
    if sort == "name":
        return func.lower(_EW.name), False
    if sort == "last_active":
        return func.coalesce(_EW.last_active_at, _NEVER), True
    return _EW.created_at, True


def sort_value(worker: ExtensionWorker, sort: str) -> Any:
    if sort == "name":
        return worker.name.lower()
    if sort == "last_active":
        return worker.last_active_at or _NEVER
    return worker.created_at


@dataclass(frozen=True)
class TopicRow:
    worker_id: uuid.UUID
    form_id: uuid.UUID
    form_name: str
    code: str | None
    status: str
    joined_at: datetime
    left_at: datetime | None


def _topics_query() -> Any:
    return (
        select(
            FormAssignment.extension_worker_id,
            Form.id,
            Form.name,
            JoinCode.code,
            FormAssignment.status,
            FormAssignment.created_at,
            FormAssignment.left_at,
        )
        .join(Form, Form.id == FormAssignment.form_id)
        .outerjoin(JoinCode, JoinCode.id == FormAssignment.joined_via_code_id)
    )


def _topic(row: Any) -> TopicRow:
    return TopicRow(row[0], row[1], row[2], row[3], row[4], row[5], row[6])


async def list_latest_topics(
    db: AsyncSession, workspace_id: uuid.UUID, worker_ids: list[uuid.UUID]
) -> list[TopicRow]:
    """Each worker's most recent active topic with the code they joined by."""
    if not worker_ids:
        return []
    rows = await db.execute(
        _topics_query()
        .where(
            FormAssignment.workspace_id == workspace_id,
            FormAssignment.extension_worker_id.in_(worker_ids),
            FormAssignment.status == "active",
        )
        .order_by(FormAssignment.extension_worker_id, FormAssignment.updated_at.desc())
        .ext(distinct_on(FormAssignment.extension_worker_id))
    )
    return [_topic(r) for r in rows.all()]


async def list_worker_topics(
    db: AsyncSession, workspace_id: uuid.UUID, worker_id: uuid.UUID
) -> list[TopicRow]:
    """Every topic of one worker, active first, then newest."""
    rows = await db.execute(
        _topics_query()
        .where(
            FormAssignment.workspace_id == workspace_id,
            FormAssignment.extension_worker_id == worker_id,
        )
        .order_by((FormAssignment.status == "active").desc(), FormAssignment.created_at.desc())
    )
    return [_topic(r) for r in rows.all()]


async def count_topics(db: AsyncSession, worker_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not worker_ids:
        return {}
    rows = await db.execute(
        select(FormAssignment.extension_worker_id, func.count())
        .where(
            FormAssignment.extension_worker_id.in_(worker_ids),
            FormAssignment.status == "active",
        )
        .group_by(FormAssignment.extension_worker_id)
    )
    return {r[0]: r[1] for r in rows.all()}


async def region_names(db: AsyncSession, region_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not region_ids:
        return {}
    rows = await db.execute(
        select(ReferenceData.id, ReferenceData.value).where(ReferenceData.id.in_(region_ids))
    )
    return {r[0]: r[1] for r in rows.all()}


async def count_by_status(db: AsyncSession, workspace_id: uuid.UUID) -> dict[str, int]:
    rows = await db.execute(
        select(_EW.status, func.count())
        .where(_EW.workspace_id == workspace_id)
        .group_by(_EW.status)
    )
    return {r[0]: r[1] for r in rows.all()}


async def count_joined_since(db: AsyncSession, workspace_id: uuid.UUID, since: datetime) -> int:
    return (
        await db.scalar(
            select(func.count()).where(
                _EW.workspace_id == workspace_id, _EW.status == "active", _EW.joined_at >= since
            )
        )
        or 0
    )


async def count_manual_approval_forms(db: AsyncSession, workspace_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(JoinCode)
            .join(Form, Form.id == JoinCode.form_id)
            .where(
                JoinCode.workspace_id == workspace_id,
                JoinCode.status != "revoked",
                JoinCode.approval_mode == "manual",
                Form.status != "archived",
            )
        )
        or 0
    )


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


async def clear_chat_contexts(db: AsyncSession, assignment_ids: list[uuid.UUID]) -> None:
    """Chats pointing at these topics no longer have an active topic."""
    if assignment_ids:
        await db.execute(
            update(ChatContext)
            .where(ChatContext.active_assignment_id.in_(assignment_ids))
            .values(active_assignment_id=None)
        )
