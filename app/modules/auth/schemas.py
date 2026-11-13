import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def _normalize_email(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    _normalize = field_validator("email", mode="before")(_normalize_email)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str


class MembershipOut(BaseModel):
    workspace_id: uuid.UUID
    workspace_name: str
    workspace_type: Literal["personal", "organization"]
    role: Literal["admin", "form_editor", "reviewer"]


class MeResponse(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]
