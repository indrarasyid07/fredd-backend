import uuid
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activity.models import ActivityEvent
from app.modules.extension_workers.models import ExtensionWorker

EventRow = tuple[ActivityEvent, str | None]


async def list_events(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    type: str | None,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[EventRow]:
    stmt = (
        select(ActivityEvent, ExtensionWorker.name)
        .outerjoin(ExtensionWorker, ExtensionWorker.id == ActivityEvent.extension_worker_id)
        .where(ActivityEvent.workspace_id == workspace_id)
    )
    if type is not None:
        stmt = stmt.where(ActivityEvent.type == type)
    if after is not None:
        occurred, last_id = after
        stmt = stmt.where(
            or_(
                ActivityEvent.occurred_at < occurred,
                and_(ActivityEvent.occurred_at == occurred, ActivityEvent.id < last_id),
            )
        )
    rows = await db.execute(
        stmt.order_by(ActivityEvent.occurred_at.desc(), ActivityEvent.id.desc()).limit(limit + 1)
    )
    return [(row[0], row[1]) for row in rows.all()]


async def latest_by_conversation(
    db: AsyncSession, workspace_id: uuid.UUID, conversation_ids: list[uuid.UUID], type: str
) -> dict[uuid.UUID, ActivityEvent]:
    """The newest event of one type for each conversation."""
    if not conversation_ids:
        return {}
    rows = await db.scalars(
        select(ActivityEvent)
        .where(
            ActivityEvent.workspace_id == workspace_id,
            ActivityEvent.conversation_id.in_(conversation_ids),
            ActivityEvent.type == type,
        )
        .order_by(ActivityEvent.conversation_id, ActivityEvent.occurred_at.desc())
        .ext(distinct_on(ActivityEvent.conversation_id))
    )
    return {e.conversation_id: e for e in rows if e.conversation_id is not None}
