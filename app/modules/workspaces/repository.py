"""All database access for workspaces. Never commits; the service owns the transaction."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.workspaces.models import Member, Workspace


async def get_personal_workspace(db: AsyncSession, user_id: uuid.UUID) -> Workspace | None:
    return await db.scalar(select(Workspace).where(Workspace.personal_owner_id == user_id))


async def create_personal_workspace(
    db: AsyncSession, *, user_id: uuid.UUID, name: str
) -> uuid.UUID | None:
    """Insert the user's personal workspace; returns None when another request already made it."""
    return await db.scalar(
        insert(Workspace)
        .values(id=uuid.uuid7(), name=name, type="personal", personal_owner_id=user_id)
        .on_conflict_do_nothing(index_elements=[Workspace.personal_owner_id])
        .returning(Workspace.id)
    )


async def create_member(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    approved_at: datetime | None,
) -> Member:
    member = Member(workspace_id=workspace_id, user_id=user_id, role=role, approved_at=approved_at)
    db.add(member)
    await db.flush()
    return member
