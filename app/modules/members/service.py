"""Members of the active workspace: list, change role, remove, invite by email, audit log.

The router requires admin for everything except reading and accepting an invite link."""

import uuid
from datetime import datetime, timedelta

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import mail
from app.core.pagination import InvalidCursor
from app.core.security import hash_token, new_token
from app.core.time import now_utc
from app.modules.audit import service as audit
from app.modules.auth.models import User
from app.modules.members import emails, errors, repository
from app.modules.members.models import MemberInvite
from app.modules.members.schemas import (
    AcceptedInvite,
    AuditLogOut,
    CreateInviteRequest,
    InviteOut,
    InvitePreview,
    MemberOut,
)
from app.modules.workspaces.constants import Role
from app.modules.workspaces.models import Member
from app.modules.workspaces.service import ActiveMember

INVITE_TTL = timedelta(days=7)  # agreed with the product owner (B-055)


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


Key = tuple[datetime, uuid.UUID]


def _key(after: list[str] | None) -> Key | None:
    """Turn a decoded cursor [timestamp, id] back into its sort key."""
    if after is None:
        return None
    try:
        return datetime.fromisoformat(after[0]), uuid.UUID(after[1])
    except ValueError:
        raise InvalidCursor() from None


async def list_members(
    db: AsyncSession, actor: ActiveMember, *, after: list[str] | None, limit: int
) -> tuple[list[MemberOut], Key | None]:
    """One page, oldest first, and the cursor key of its last row when more rows exist."""
    key = _key(after)
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


# --- Invites (B-055) ------------------------------------------------------------------------------


def _invite_out(invite: MemberInvite, inviter: str | None, now: datetime) -> InviteOut:
    return InviteOut(
        id=invite.id,
        email=invite.email,
        role=invite.role,  # pyright: ignore[reportArgumentType]  # CHECK constraint
        status="pending" if invite.expires_at > now else "expired",
        invited_by_name=inviter,
        sent_at=invite.sent_at,
        expires_at=invite.expires_at,
    )


async def list_invites(
    db: AsyncSession, actor: ActiveMember, *, after: list[str] | None, limit: int
) -> tuple[list[InviteOut], Key | None]:
    """Open invites (pending or expired), newest first."""
    rows = await repository.list_open_invites(
        db, actor.workspace_id, after=_key(after), limit=limit
    )
    page, now = rows[:limit], now_utc()
    more = (page[-1][0].sent_at, page[-1][0].id) if len(rows) > limit else None
    return [_invite_out(invite, name, now) for invite, name in page], more


def _send_invite(
    background: BackgroundTasks,
    invite: MemberInvite,
    token: str,
    actor: ActiveMember,
    inviter: User,
) -> None:
    subject, body = emails.invite(
        token=token, workspace_name=actor.workspace.name, role=invite.role, inviter=inviter.name
    )
    background.add_task(mail.send_email, invite.email, subject, body)


async def invite(
    db: AsyncSession,
    actor: ActiveMember,
    inviter: User,
    data: CreateInviteRequest,
    background: BackgroundTasks,
) -> InviteOut:
    """Invite an email. Inviting an address that already has an open invite reissues that invite
    (new link, the new role, 7 more days) instead of failing."""
    if actor.workspace.type == "personal":
        raise errors.PersonalWorkspace()
    existing = await repository.get_member_by_email(db, actor.workspace_id, data.email)
    if existing is not None and existing.approved_at is not None:
        raise errors.AlreadyMember(field="email")
    token, now = new_token(), now_utc()
    values = {
        "role": data.role,
        "token_hash": hash_token(token),
        "invited_by_user_id": inviter.id,
        "sent_at": now,
        "expires_at": now + INVITE_TTL,
    }
    invite = await repository.get_open_invite_by_email(db, actor.workspace_id, data.email)
    if invite is None:
        invite = await repository.create_invite(
            db, MemberInvite(workspace_id=actor.workspace_id, email=data.email, **values)
        )
    else:
        await repository.update_invite(db, invite, **values)
        await db.refresh(invite)
    await audit.record(
        db,
        workspace_id=actor.workspace_id,
        actor_user_id=inviter.id,
        action="member.invited",
        target=f"invite:{invite.id}",
        details={"email": invite.email, "role": invite.role},
    )
    await db.commit()
    _send_invite(background, invite, token, actor, inviter)
    return _invite_out(invite, inviter.name, now)


async def _open_invite(db: AsyncSession, actor: ActiveMember, invite_id: uuid.UUID) -> MemberInvite:
    invite = await repository.get_open_invite(db, actor.workspace_id, invite_id)
    if invite is None:
        raise errors.InviteNotFound()
    return invite


async def resend_invite(
    db: AsyncSession,
    actor: ActiveMember,
    inviter: User,
    invite_id: uuid.UUID,
    background: BackgroundTasks,
) -> InviteOut:
    """New link and 7 more days; the old link stops working."""
    invite = await _open_invite(db, actor, invite_id)
    token, now = new_token(), now_utc()
    await repository.update_invite(
        db,
        invite,
        token_hash=hash_token(token),
        invited_by_user_id=inviter.id,
        sent_at=now,
        expires_at=now + INVITE_TTL,
    )
    await db.refresh(invite)
    await audit.record(
        db,
        workspace_id=actor.workspace_id,
        actor_user_id=inviter.id,
        action="member.invite_resent",
        target=f"invite:{invite.id}",
        details={"email": invite.email},
    )
    await db.commit()
    _send_invite(background, invite, token, actor, inviter)
    return _invite_out(invite, inviter.name, now)


async def revoke_invite(db: AsyncSession, actor: ActiveMember, invite_id: uuid.UUID) -> None:
    invite = await _open_invite(db, actor, invite_id)
    await repository.update_invite(db, invite, revoked_at=now_utc())
    await audit.record(
        db,
        workspace_id=actor.workspace_id,
        actor_user_id=actor.member.user_id,
        action="member.invite_revoked",
        target=f"invite:{invite.id}",
        details={"email": invite.email},
    )
    await db.commit()


async def preview_invite(db: AsyncSession, token: str) -> InvitePreview:
    found = await repository.get_usable_invite(db, hash_token(token), now_utc())
    if found is None:
        raise errors.InviteInvalid(field="token")
    invite, workspace, inviter = found
    return InvitePreview(
        workspace_name=workspace.name,
        email=invite.email,
        role=invite.role,  # pyright: ignore[reportArgumentType]  # CHECK constraint
        invited_by_name=inviter,
        expires_at=invite.expires_at,
    )


async def accept_invite(db: AsyncSession, user: User, token: str) -> AcceptedInvite:
    """Join the workspace right away (no admin approval, B-055). Only the invited email may accept;
    an existing pending membership is approved with the invited role, an active one is kept."""
    now = now_utc()
    found = await repository.get_usable_invite(db, hash_token(token), now, lock=True)
    if found is None:
        raise errors.InviteInvalid(field="token")
    invite, workspace, _ = found
    if user.email != invite.email:
        raise errors.InviteEmailMismatch()
    member = await repository.get_member_by_user(db, workspace.id, user.id)
    if member is None:
        member = await repository.create_member(
            db, workspace_id=workspace.id, user_id=user.id, role=invite.role, now=now
        )
    elif member.approved_at is None:
        await repository.approve_member(db, member, invite.role, now)
        await db.refresh(member)
    await repository.update_invite(db, invite, accepted_at=now)
    await audit.record(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        action="member.joined",
        target=f"member:{member.id}",
        details={"invite_id": str(invite.id), "role": member.role},
    )
    await db.commit()
    return AcceptedInvite(
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        role=member.role,  # pyright: ignore[reportArgumentType]  # CHECK constraint
    )


# --- Audit log ------------------------------------------------------------------------------------


async def list_audit_logs(
    db: AsyncSession, actor: ActiveMember, *, after: list[str] | None, limit: int
) -> tuple[list[AuditLogOut], Key | None]:
    rows = await repository.list_audit_logs(db, actor.workspace_id, after=_key(after), limit=limit)
    page = rows[:limit]
    more = (page[-1][0].created_at, page[-1][0].id) if len(rows) > limit else None
    return [
        AuditLogOut(
            id=entry.id,
            action=entry.action,
            target=entry.target,
            details=entry.details,
            actor_name=name,
            created_at=entry.created_at,
        )
        for entry, name in page
    ], more
