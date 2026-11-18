"""Workspace rules.

This module sits right above auth in the dependency order but only needs a user id, so auth may
call `ensure_personal_workspace` without a cycle (B-050). It never imports auth.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.workspaces import repository
from app.modules.workspaces.models import Workspace


def personal_workspace_name(user_name: str) -> str:
    return user_name.strip()[:200] or "Workspace Perorangan"


async def ensure_personal_workspace(
    db: AsyncSession, *, user_id: uuid.UUID, user_name: str
) -> Workspace:
    """Give a verified user their personal workspace (free plan) with them as admin.

    Idempotent and safe under concurrent sign-ins; the caller commits.
    """
    existing = await repository.get_personal_workspace(db, user_id)
    if existing is not None:
        return existing
    workspace_id = await repository.create_personal_workspace(
        db, user_id=user_id, name=personal_workspace_name(user_name)
    )
    if workspace_id is not None:
        await repository.create_member(
            db, workspace_id=workspace_id, user_id=user_id, role="admin", approved_at=now_utc()
        )
    workspace = await repository.get_personal_workspace(db, user_id)
    assert workspace is not None
    return workspace
