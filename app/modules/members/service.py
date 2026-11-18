"""Members of the active workspace: list, change role, remove (the router requires admin)."""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import InvalidCursor
from app.modules.audit import service as audit
from app.modules.members import errors, repository
from app.modules.members.schemas import MemberOut
from app.modules.workspaces.constants import Role
from app.modules.workspaces.models import Member
from app.modules.workspaces.service import ActiveMember


def _out(member: Member, name: str, email: str, last_active: datetime | None) -> MemberOut:
    return MemberOut(
        id=member.id,
        user_id=member.user_id,
        name=name,
        email=email,
        role=member.role,  # pyright: ignore[reportArgumentType]  # CHECK constraint
        status="active" if member.approved_at is not None else "pending",
        joined_at=member.created_at,
        last_active_at=last_active,
    )


async def list_members(
    db: AsyncSession, actor: ActiveMember, *, after: list[str] | None, limit: int
) -> tuple[list[MemberOut], tuple[datetime, uuid.UUID] | None]:
    """One page, oldest first, and the cursor key of its last row when more rows exist."""
    key = None
    if after is not None:
        try:
            key = (datetime.fromisoformat(after[0]), uuid.UUID(after[1]))
        except ValueError:
            raise InvalidCursor() from None
    rows = await repository.list_members(db, actor.workspace_id, after=key, limit=limit)
    page = rows[:limit]
    more = (page[-1][0].created_at, page[-1][0].id) if len(rows) > limit else None
    return [_out(*row) for row in page], more


async def _get(db: AsyncSession, actor: ActiveMember, member_id: uuid.UUID) -> Member:
    member = await repository.get_member(db, actor.workspace_id, member_id)
    if member is None:
        raise errors.MemberNotFound()
    return member


async def _keep_an_admin(db: AsyncSession, actor: ActiveMember, member: Member) -> None:
    """Raise when `member` is the workspace's last approved admin (locks admin rows meanwhile)."""
    is_admin = member.role == "admin" and member.approved_at is not None
    if is_admin and await repository.count_approved_admins(db, actor.workspace_id) <= 1:
        raise errors.LastAdmin()


async def change_role(
    db: AsyncSession, actor: ActiveMember, member_id: uuid.UUID, role: Role
) -> None:
    member = await _get(db, actor, member_id)
    if member.role == role:
        return
    if role != "admin":
        await _keep_an_admin(db, actor, member)
    previous = member.role
    await repository.set_role(db, member, role)
    await audit.record(
        db,
        workspace_id=actor.workspace_id,
        actor_user_id=actor.member.user_id,
        action="member.role_changed",
        target=f"member:{member.id}",
        details={"from": previous, "to": role},
    )
    await db.commit()


async def remove(db: AsyncSession, actor: ActiveMember, member_id: uuid.UUID) -> None:
    member = await _get(db, actor, member_id)
    await _keep_an_admin(db, actor, member)
    await repository.delete_member(db, member)
    await audit.record(
        db,
        workspace_id=actor.workspace_id,
        actor_user_id=actor.member.user_id,
        action="member.removed",
        target=f"member:{member.id}",
        details={"user_id": str(member.user_id), "role": member.role},
    )
    await db.commit()
