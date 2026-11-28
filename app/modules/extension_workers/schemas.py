import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ExtensionWorkerStatus = Literal["pending_approval", "active", "left", "blocked", "unreachable"]
WorkerSort = Literal["newest", "last_active", "name"]


class WorkerTopicOut(BaseModel):
    """The structure the worker asked to join, and the code they used."""

    form_id: uuid.UUID
    form_name: str
    # Display form, e.g. K7M2-9QXA; null when the code was deleted.
    join_code: str | None


class WorkerRegionOut(BaseModel):
    id: uuid.UUID
    name: str


class ExtensionWorkerOut(BaseModel):
    id: uuid.UUID
    name: str
    status: ExtensionWorkerStatus
    # Why a request waits: "manual" approval or the plan's worker "quota".
    pending_reason: Literal["manual", "quota"] | None
    channel: Literal["telegram", "whatsapp"]
    telegram_username: str | None
    phone_e164: str | None
    region: WorkerRegionOut | None
    joined_at: datetime | None
    # When the worker answered "Ya, tetap"; null while the binding is unconfirmed.
    confirmed_at: datetime | None
    # Their latest message to a topic of this organization.
    last_active_at: datetime | None
    # The most recent active topic; null when the worker has none.
    topic: WorkerTopicOut | None
    # Active topics in this organization, including `topic`.
    topic_count: int


class WorkerTopicDetailOut(BaseModel):
    form_id: uuid.UUID
    form_name: str
    status: Literal["active", "left"]
    join_code: str | None
    joined_at: datetime
    left_at: datetime | None


class ExtensionWorkerDetailOut(ExtensionWorkerOut):
    # "channel_profile" (from the chat at first contact) or "admin" (edited in the dashboard).
    name_source: Literal["channel_profile", "admin"]
    # Every topic in this organization, newest first, including ones they left.
    topics: list[WorkerTopicDetailOut]


class ExtensionWorkerSummaryOut(BaseModel):
    """Counts for the list's tabs and KPI cards (no report numbers: those come with reports)."""

    total: int
    active: int
    pending_approval: int
    # left + blocked + unreachable
    inactive: int
    # Active workers who joined in the last 7 days.
    new_this_week: int
    # Structures (not archived) whose join code needs an admin's approval.
    manual_approval_forms: int


class UpdateExtensionWorkerRequest(BaseModel):
    """Only the fields sent change. `region_id: null` clears the region."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    region_id: uuid.UUID | None = None


class MoveIdentityRequest(BaseModel):
    """The record made when the worker joined again from their new phone or Telegram account."""

    from_extension_worker_id: uuid.UUID
