import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ExtensionWorkerStatus = Literal["pending_approval", "active", "left", "blocked", "unreachable"]


class WorkerTopicOut(BaseModel):
    """The structure the worker asked to join, and the code they used."""

    form_id: uuid.UUID
    form_name: str
    # Display form, e.g. K7M2-9QXA; null when the code was deleted.
    join_code: str | None


class ExtensionWorkerOut(BaseModel):
    id: uuid.UUID
    name: str
    status: ExtensionWorkerStatus
    # Why a request waits: "manual" approval or the plan's worker "quota".
    pending_reason: Literal["manual", "quota"] | None
    channel: Literal["telegram", "whatsapp"]
    telegram_username: str | None
    phone_e164: str | None
    joined_at: datetime | None
    # When the worker answered "Ya, tetap"; null while the binding is unconfirmed.
    confirmed_at: datetime | None
    # The most recent topic; null when the worker has none.
    topic: WorkerTopicOut | None
