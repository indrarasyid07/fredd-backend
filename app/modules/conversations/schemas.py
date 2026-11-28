import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.modules.activity.schemas import ActivityWorkerOut


class ConversationFormOut(BaseModel):
    id: uuid.UUID
    name: str


class ConversationHelpOut(BaseModel):
    """Why the bot handed the conversation to an admin."""

    reason: Literal["failed_attempts", "asked_for_help"]
    # Key and label of the field the worker was stuck on, when there was one.
    field: str | None
    field_label: str | None
    at: datetime


class ConversationOut(BaseModel):
    id: uuid.UUID
    status: str
    channel: Literal["telegram", "whatsapp"]
    extension_worker: ActivityWorkerOut
    form: ConversationFormOut
    # Key of the field being asked.
    step: str | None
    last_inbound_at: datetime | None
    updated_at: datetime
    # Set while status is `needs_help`.
    help: ConversationHelpOut | None


class ConversationMessageOut(BaseModel):
    id: uuid.UUID
    direction: Literal["in", "out"]
    kind: str
    body: str | None
    # Outgoing only. Telegram never reports "read"; WhatsApp may add delivered/read.
    delivery_status: str | None
    created_at: datetime


class ConversationDetailOut(ConversationOut):
    # The latest messages, oldest first (at most 50).
    messages: list[ConversationMessageOut]
