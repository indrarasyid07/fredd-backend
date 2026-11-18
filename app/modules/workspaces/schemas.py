import uuid

from pydantic import BaseModel

from app.modules.workspaces.constants import Role, WorkspaceType


class MembershipOut(BaseModel):
    workspace_id: uuid.UUID
    workspace_name: str
    workspace_type: WorkspaceType
    role: Role
