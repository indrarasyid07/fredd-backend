"""Write and read the Aktivitas Agent log. `record` joins the caller's transaction."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import InvalidCursor
from app.core.time import now_utc
from app.modules.activity import repository
from app.modules.activity.models import ActivityEvent
from app.modules.activity.schemas import ActivityEventOut, ActivityWorkerOut
from app.modules.workspaces.service import ActiveMember

Key = tuple[datetime, uuid.UUID]


async def record(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    type: str,
    status: str,
    channel: str | None = None,
    extension_worker_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        ActivityEvent(
            workspace_id=workspace_id,
            occurred_at=now_utc(),
            type=type,
            status=status,
            channel=channel,
            extension_worker_id=extension_worker_id,
            conversation_id=conversation_id,
            details=details or {},
        )
    )
    await db.flush()


def _key(after: list[str] | None) -> Key | None:
    if after is None:
        return None
    try:
        return datetime.fromisoformat(after[0]), uuid.UUID(after[1])
    except ValueError:
        raise InvalidCursor() from None


async def list_events(
    db: AsyncSession,
    member: ActiveMember,
    *,
    type: str | None,
    after: list[str] | None,
    limit: int,
) -> tuple[list[ActivityEventOut], Key | None]:
    rows = await repository.list_events(
        db, member.workspace_id, type=type, after=_key(after), limit=limit
    )
    page = rows[:limit]
    more = (page[-1][0].occurred_at, page[-1][0].id) if len(rows) > limit else None
    return [
        ActivityEventOut(
            id=event.id,
            occurred_at=event.occurred_at,
            type=event.type,  # type: ignore[arg-type]
            status=event.status,  # type: ignore[arg-type]
            channel=event.channel,  # type: ignore[arg-type]
            extension_worker=(
                ActivityWorkerOut(id=event.extension_worker_id, name=name)
                if event.extension_worker_id is not None and name is not None
                else None
            ),
            conversation_id=event.conversation_id,
            details=event.details,
        )
        for event, name in page
    ], more


async def latest_help(
    db: AsyncSession, workspace_id: uuid.UUID, conversation_ids: list[uuid.UUID]
) -> dict[uuid.UUID, ActivityEvent]:
    """Why each conversation asked for an admin: its newest `needs_help` event."""
    return await repository.latest_by_conversation(db, workspace_id, conversation_ids, "needs_help")
