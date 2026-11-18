import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.modules.workspaces.constants import Role


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    email: str
    role: Role
    # "pending" = invited or requested, not approved yet; such members have no access.
    status: Literal["active", "pending"]
    joined_at: datetime
    last_active_at: datetime | None


class UpdateMemberRequest(BaseModel):
    role: Role


def _normalize_email(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


class CreateInviteRequest(BaseModel):
    email: EmailStr
    role: Role

    _normalize = field_validator("email", mode="before")(_normalize_email)


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str
    role: Role
    # "expired" invites stay listed so the admin can resend them.
    status: Literal["pending", "expired"]
    invited_by_name: str | None
    sent_at: datetime
    expires_at: datetime


class InviteTokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class InvitePreview(BaseModel):
    """What the /invite/[token] page shows before the person accepts."""

    workspace_name: str
    email: str
    role: Role
    invited_by_name: str | None
    expires_at: datetime


class AcceptedInvite(BaseModel):
    workspace_id: uuid.UUID
    workspace_name: str
    role: Role


class AuditLogOut(BaseModel):
    id: uuid.UUID
    action: str  # "member.invited", "member.role_changed", ...
    target: str | None
    details: dict[str, Any]
    actor_name: str | None  # null when the actor's account was deleted
    created_at: datetime
