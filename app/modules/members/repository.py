"""Member listing joins workspaces.members with auth.users/sessions, so it lives above both modules
(B-053). Never commits."""

import uuid
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import in_workspace
from app.modules.auth.models import Session, User
from app.modules.workspaces.models import Member

Row = tuple[Member, str, str, datetime | None]


async def list_members(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[Row]:
    last_active = (
        select(func.max(Session.last_seen_at))
        .where(Session.user_id == Member.user_id)
        .correlate(Member)
        .scalar_subquery()
    )
    stmt = in_workspace(
        select(Member, User.name, User.email, last_active).join(User, User.id == Member.user_id),
        Member,
        workspace_id,
    )
    if after is not None:
        created, last_id = after
        stmt = stmt.where(
            or_(
                Member.created_at > created, and_(Member.created_at == created, Member.id > last_id)
            )
        )
    rows = await db.execute(stmt.order_by(Member.created_at, Member.id).limit(limit + 1))
    return [(row[0], row[1], row[2], row[3]) for row in rows.all()]


async def get_member(
    db: AsyncSession, workspace_id: uuid.UUID, member_id: uuid.UUID
) -> Member | None:
    return await db.scalar(
        select(Member).where(Member.workspace_id == workspace_id, Member.id == member_id)
    )


async def count_approved_admins(db: AsyncSession, workspace_id: uuid.UUID) -> int:
    """Locks the admin rows (FOR UPDATE) so two admins cannot demote each other at once."""
    ids = await db.scalars(
        select(Member.id)
        .where(
            Member.workspace_id == workspace_id,
            Member.role == "admin",
            Member.approved_at.is_not(None),
        )
        .with_for_update()
    )
    return len(ids.all())


async def set_role(db: AsyncSession, member: Member, role: str) -> None:
    await db.execute(update(Member).where(Member.id == member.id).values(role=role))


async def delete_member(db: AsyncSession, member: Member) -> None:
    await db.execute(delete(Member).where(Member.id == member.id))
