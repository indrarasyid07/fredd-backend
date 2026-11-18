"""Workspace rules.

This module sits right above auth in the dependency order but only needs a user id, so auth may
call `ensure_personal_workspace` without a cycle (B-050). It never imports auth.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.workspaces import errors, repository
from app.modules.workspaces.models import Member, Workspace
from app.modules.workspaces.schemas import MembershipOut


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
