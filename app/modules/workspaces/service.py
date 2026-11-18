"""Workspace rules.

This module sits right above auth in the dependency order but only needs a user id, so auth may
call `ensure_personal_workspace` without a cycle (B-050). It never imports auth.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.audit import service as audit
from app.modules.workspaces import errors, repository
from app.modules.workspaces.constants import (
    DEFAULT_DATE_FORMAT,
    DEFAULT_WEEK_START,
    ROLES,
    Role,
)
from app.modules.workspaces.models import Member, Workspace
from app.modules.workspaces.schemas import (
    MembershipOut,
    OperatingHours,
    QuietHours,
    UpdateWorkspaceRequest,
    WorkspaceOut,
)

# Display preferences stored in workspaces.settings next to other keys (seed_key, thresholds).
_SETTINGS_KEYS = ("org_type", "date_format", "week_start")


@dataclass(frozen=True)
class ActiveMember:
    """The signed-in user inside the workspace named by `X-Workspace-Id` (B-051)."""

    workspace: Workspace
    member: Member

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.workspace.id

    @property
    def role(self) -> str:
        return self.member.role


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


async def list_memberships(db: AsyncSession, user_id: uuid.UUID) -> list[MembershipOut]:
    """Approved memberships, personal workspace first; pending ones grant nothing."""
    return [
        MembershipOut(
            workspace_id=w.id,
            workspace_name=w.name,
            workspace_type=w.type,  # pyright: ignore[reportArgumentType]  # CHECK constraint
            role=m.role,  # pyright: ignore[reportArgumentType]  # CHECK constraint
        )
        for m, w in await repository.list_approved_memberships(db, user_id)
    ]


async def get_active_member(
    db: AsyncSession, *, user_id: uuid.UUID, workspace_id: str | None
) -> ActiveMember:
    """Resolve the `X-Workspace-Id` header against the user's approved memberships."""
    if not workspace_id:
        raise errors.WorkspaceRequired()
    try:
        parsed = uuid.UUID(workspace_id)
    except ValueError:
        raise errors.WorkspaceNotFound() from None
    found = await repository.get_approved_membership(db, user_id=user_id, workspace_id=parsed)
    if found is None:
        raise errors.WorkspaceNotFound()
    member, workspace = found
    return ActiveMember(workspace=workspace, member=member)


def role_at_least(role: str, min_role: Role) -> bool:
    """reviewer < form_editor < admin (security-model.md#peran)."""
    return ROLES.index(role) >= ROLES.index(min_role)  # pyright: ignore[reportArgumentType]


def check_role(member: ActiveMember, min_role: Role) -> ActiveMember:
    if not role_at_least(member.role, min_role):
        raise errors.RoleTooLow()
    return member


async def seed_organization(
    db: AsyncSession, *, name: str, seed_key: str, members: list[tuple[uuid.UUID, Role]]
) -> Workspace:
    """Development seed only: an organization found by `seed_key`, with each user at the given role.

    Idempotent: reruns reuse the workspace and reset roles to the fixture's values.
    """
    workspace = await repository.get_organization_by_seed_key(db, seed_key)
    if workspace is None:
        workspace = await repository.create_organization(
            db, name=name, settings={"seed_key": seed_key}
        )
    now = now_utc()
    for user_id, role in members:
        member = await repository.get_member(db, workspace_id=workspace.id, user_id=user_id)
        if member is None:
            await repository.create_member(
                db, workspace_id=workspace.id, user_id=user_id, role=role, approved_at=now
            )
        elif member.role != role or member.approved_at is None:
            await repository.update_member_role(db, member, role, now)
    await db.commit()
    return workspace


# --- Pengaturan Umum (Langkah 1.5) ----------------------------------------------------------------


async def get_settings(db: AsyncSession, member: ActiveMember) -> WorkspaceOut:
    ws = member.workspace
    prefs = ws.settings or {}
    return WorkspaceOut(
        id=ws.id,
        name=ws.name,
        type=ws.type,  # pyright: ignore[reportArgumentType]  # CHECK constraint
        org_type=prefs.get("org_type"),
        timezone=ws.timezone,  # pyright: ignore[reportArgumentType]  # validated on write
        date_format=prefs.get("date_format", DEFAULT_DATE_FORMAT),
        week_start=prefs.get("week_start", DEFAULT_WEEK_START),
        operating_hours=OperatingHours(**ws.operating_hours) if ws.operating_hours else None,
        quiet_hours=QuietHours(**ws.quiet_hours) if ws.quiet_hours else None,
        retention_conversations_months=ws.retention_conversations_months,
        retention_photos_months=ws.retention_photos_months,
        require_sso=ws.require_sso,
        member_count=await repository.count_approved_members(db, ws.id),
        created_at=ws.created_at,
    )


async def update_settings(
    db: AsyncSession, member: ActiveMember, data: UpdateWorkspaceRequest
) -> WorkspaceOut:
    """Apply the fields present in the request (admin only; the router checks the role)."""
    ws = member.workspace
    given = data.model_dump(exclude_unset=True)
    values: dict[str, object] = {}
    prefs = dict(ws.settings or {})
    for key, value in given.items():
        if key in _SETTINGS_KEYS:
            if value is None:
                prefs.pop(key, None)
            else:
                prefs[key] = value
        elif key in (
            "name",
            "timezone",
            "retention_conversations_months",
            "retention_photos_months",
        ):
            if value is not None:  # these columns are never null
                values[key] = value
        else:  # operating_hours / quiet_hours: null clears
            values[key] = value
    if prefs != (ws.settings or {}):
        values["settings"] = prefs
    changed = sorted(k for k in values if getattr(ws, k) != values[k])
    if changed:
        await repository.update_workspace(db, ws, values)
        await audit.record(
            db,
            workspace_id=ws.id,
            actor_user_id=member.member.user_id,
            action="workspace.updated",
            target=f"workspace:{ws.id}",
            details={"fields": changed},
        )
        await db.commit()
        await db.refresh(ws)
    return await get_settings(db, member)
