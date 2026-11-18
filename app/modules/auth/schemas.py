import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.workspaces.schemas import MembershipOut


def _normalize_email(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    _normalize = field_validator("email", mode="before")(_normalize_email)


class RegisterRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    organization: str | None = Field(default=None, max_length=200)
    password: str = Field(max_length=128)  # strength is checked in the service (weak_password)
    accept_terms: bool

    _normalize = field_validator("email", mode="before")(_normalize_email)


class EmailRequest(BaseModel):
    """Body of verify-email/resend and password/forgot."""

    email: EmailStr

    _normalize = field_validator("email", mode="before")(_normalize_email)


class TokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class ResetPasswordRequest(TokenRequest):
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str


class MeResponse(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]
