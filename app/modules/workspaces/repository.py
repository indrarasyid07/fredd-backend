"""All database access for workspaces. Never commits; the service owns the transaction."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
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


async def list_approved_memberships(
    db: AsyncSession, user_id: uuid.UUID
) -> list[tuple[Member, Workspace]]:
    rows = await db.execute(
        select(Member, Workspace)
        .join(Workspace, Workspace.id == Member.workspace_id)
        .where(Member.user_id == user_id, Member.approved_at.is_not(None))
        # Personal first, then organizations by name.
        .order_by((Workspace.type == "personal").desc(), Workspace.name)
    )
    return [(m, w) for m, w in rows.all()]


async def get_approved_membership(
    db: AsyncSession, *, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> tuple[Member, Workspace] | None:
    row = (
        await db.execute(
            select(Member, Workspace)
            .join(Workspace, Workspace.id == Member.workspace_id)
            .where(
                Member.user_id == user_id,
                Member.workspace_id == workspace_id,
                Member.approved_at.is_not(None),
            )
        )
    ).first()
    return (row[0], row[1]) if row else None


async def get_organization_by_seed_key(db: AsyncSession, seed_key: str) -> Workspace | None:
    return await db.scalar(
        select(Workspace).where(
            Workspace.type == "organization", Workspace.settings["seed_key"].astext == seed_key
        )
    )


async def create_organization(
    db: AsyncSession, *, name: str, settings: dict[str, str]
) -> Workspace:
    workspace = Workspace(name=name, type="organization", settings=settings)
    db.add(workspace)
    await db.flush()
    return workspace


async def get_member(
    db: AsyncSession, *, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> Member | None:
    return await db.scalar(
        select(Member).where(Member.workspace_id == workspace_id, Member.user_id == user_id)
    )


async def update_member_role(
    db: AsyncSession, member: Member, role: str, approved_at: datetime
) -> None:
    await db.execute(
        update(Member).where(Member.id == member.id).values(role=role, approved_at=approved_at)
    )


async def count_approved_members(db: AsyncSession, workspace_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(Member)
            .where(Member.workspace_id == workspace_id, Member.approved_at.is_not(None))
        )
        or 0
    )


async def update_workspace(db: AsyncSession, workspace: Workspace, values: dict[str, Any]) -> None:
    await db.execute(update(Workspace).where(Workspace.id == workspace.id).values(**values))


async def get_name(db: AsyncSession, workspace_id: uuid.UUID) -> str | None:
    return await db.scalar(select(Workspace.name).where(Workspace.id == workspace_id))


async def get_timezone(db: AsyncSession, workspace_id: uuid.UUID) -> str | None:
    return await db.scalar(select(Workspace.timezone).where(Workspace.id == workspace_id))
