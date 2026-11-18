"""Member listing joins workspaces.members with auth.users/sessions, so it lives above both modules
(B-053). Never commits."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import in_workspace
from app.modules.audit.models import AuditLog
from app.modules.auth.models import Session, User
from app.modules.members.models import MemberInvite
from app.modules.workspaces.models import Member, Workspace

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


async def get_member_by_user(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> Member | None:
    return await db.scalar(
        select(Member).where(Member.workspace_id == workspace_id, Member.user_id == user_id)
    )


async def get_member_by_email(
    db: AsyncSession, workspace_id: uuid.UUID, email: str
) -> Member | None:
    return await db.scalar(
        select(Member)
        .join(User, User.id == Member.user_id)
        .where(Member.workspace_id == workspace_id, User.email == email)
    )


async def create_member(
    db: AsyncSession, *, workspace_id: uuid.UUID, user_id: uuid.UUID, role: str, now: datetime
) -> Member:
    member = Member(workspace_id=workspace_id, user_id=user_id, role=role, approved_at=now)
    db.add(member)
    await db.flush()
    return member


async def approve_member(db: AsyncSession, member: Member, role: str, now: datetime) -> None:
    await db.execute(
        update(Member).where(Member.id == member.id).values(role=role, approved_at=now)
    )


# --- Invites --------------------------------------------------------------------------------------

InviteRow = tuple[MemberInvite, str | None]


def _open() -> list[Any]:
    return [MemberInvite.accepted_at.is_(None), MemberInvite.revoked_at.is_(None)]


async def list_open_invites(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[InviteRow]:
    stmt = in_workspace(
        select(MemberInvite, User.name).outerjoin(User, User.id == MemberInvite.invited_by_user_id),
        MemberInvite,
        workspace_id,
    ).where(*_open())
    if after is not None:
        sent, last_id = after
        stmt = stmt.where(
            or_(
                MemberInvite.sent_at < sent,
                and_(MemberInvite.sent_at == sent, MemberInvite.id < last_id),
            )
        )
    rows = await db.execute(
        stmt.order_by(MemberInvite.sent_at.desc(), MemberInvite.id.desc()).limit(limit + 1)
    )
    return [(row[0], row[1]) for row in rows.all()]


async def get_open_invite(
    db: AsyncSession, workspace_id: uuid.UUID, invite_id: uuid.UUID
) -> MemberInvite | None:
    return await db.scalar(
        select(MemberInvite)
        .where(MemberInvite.workspace_id == workspace_id, MemberInvite.id == invite_id, *_open())
        .with_for_update()
    )


async def get_open_invite_by_email(
    db: AsyncSession, workspace_id: uuid.UUID, email: str
) -> MemberInvite | None:
    return await db.scalar(
        select(MemberInvite)
        .where(MemberInvite.workspace_id == workspace_id, MemberInvite.email == email, *_open())
        .with_for_update()
    )


async def get_usable_invite(
    db: AsyncSession, token_hash: str, now: datetime, *, lock: bool = False
) -> tuple[MemberInvite, Workspace, str | None] | None:
    """The open, unexpired invite behind a link, with its workspace and the inviter's name."""
    stmt = (
        select(MemberInvite, Workspace, User.name)
        .join(Workspace, Workspace.id == MemberInvite.workspace_id)
        .outerjoin(User, User.id == MemberInvite.invited_by_user_id)
        .where(MemberInvite.token_hash == token_hash, MemberInvite.expires_at > now, *_open())
    )
    if lock:
        stmt = stmt.with_for_update(of=MemberInvite)
    row = (await db.execute(stmt)).first()
    return (row[0], row[1], row[2]) if row else None


async def create_invite(db: AsyncSession, invite: MemberInvite) -> MemberInvite:
    db.add(invite)
    await db.flush()
    return invite


async def update_invite(db: AsyncSession, invite: MemberInvite, **values: Any) -> None:
    await db.execute(update(MemberInvite).where(MemberInvite.id == invite.id).values(**values))


# --- Audit log (read side; audit.record writes it) -----------------------------------------------

AuditRow = tuple[AuditLog, str | None]


async def list_audit_logs(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[AuditRow]:
    stmt = (
        select(AuditLog, User.name)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(AuditLog.workspace_id == workspace_id)
    )
    if after is not None:
        created, last_id = after
        stmt = stmt.where(
            or_(
                AuditLog.created_at < created,
                and_(AuditLog.created_at == created, AuditLog.id < last_id),
            )
        )
    rows = await db.execute(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1)
    )
    return [(row[0], row[1]) for row in rows.all()]
