import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

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
