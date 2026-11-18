"""Append-only audit trail. Callers own the transaction, so the entry commits with the change."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog


async def record(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    action: str,
    target: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            action=action,
            target=target,
            details=details or {},
        )
    )
    await db.flush()
