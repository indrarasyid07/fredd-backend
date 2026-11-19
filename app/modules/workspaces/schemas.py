import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.modules.workspaces.constants import (
    DateFormat,
    OrgType,
    Role,
    Timezone,
    WeekStart,
    WorkspaceType,
)

Clock = Annotated[str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]


class MembershipOut(BaseModel):
    workspace_id: uuid.UUID
    workspace_name: str
    workspace_type: WorkspaceType
    role: Role


class QuietHours(BaseModel):
    """No reminders to extension workers between `start` and `end` (may cross midnight)."""

    start: Clock
    end: Clock

    @model_validator(mode="after")
    def _not_empty(self) -> QuietHours:
        if self.start == self.end:
            raise ValueError("Jam mulai dan jam selesai tidak boleh sama.")
        return self


class OperatingHours(QuietHours):
    """Working days (1 = Monday ... 7 = Sunday) and hours."""

    days: list[Annotated[int, Field(ge=1, le=7)]] = Field(min_length=1, max_length=7)


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    type: WorkspaceType
    org_type: OrgType | None
    timezone: Timezone
    date_format: DateFormat
    week_start: WeekStart
    operating_hours: OperatingHours | None
    quiet_hours: QuietHours | None
    retention_conversations_months: int
    retention_photos_months: int
    require_sso: bool
    member_count: int  # approved members
    created_at: datetime


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Months = Annotated[int, Field(ge=1, le=120)]


class UpdateWorkspaceRequest(BaseModel):
    """Only the fields present change. `operating_hours` / `quiet_hours` set to null clear them."""

    name: Name | None = None
    org_type: OrgType | None = None
    timezone: Timezone | None = None
    date_format: DateFormat | None = None
    week_start: WeekStart | None = None
    operating_hours: OperatingHours | None = None
    quiet_hours: QuietHours | None = None
    retention_conversations_months: Months | None = None
    retention_photos_months: Months | None = None
