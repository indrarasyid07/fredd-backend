import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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


class ConversationAdminOut(BaseModel):
    id: uuid.UUID
    name: str


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
    # Set while status is `needs_help`, and kept while an admin has taken it over.
    help: ConversationHelpOut | None
    # Who is answering instead of Fluctuz (roadmap 6.4); null when nobody is.
    taken_over_by: ConversationAdminOut | None
    taken_over_at: datetime | None
    # WhatsApp only: free replies are allowed until 24 hours after the worker's last message;
    # after that only templates. Null for Telegram, which has no such window.
    whatsapp_window_expires_at: datetime | None


class ConversationMessageOut(BaseModel):
    id: uuid.UUID
    direction: Literal["in", "out"]
    kind: str
    body: str | None
    # Outgoing only. Telegram never reports "read"; WhatsApp may add delivered/read.
    delivery_status: str | None
    # Set on a message an admin wrote during a takeover.
    admin_name: str | None
    created_at: datetime


class ConversationDetailOut(ConversationOut):
    # The latest messages, oldest first (at most 50).
    messages: list[ConversationMessageOut]


class SendConversationMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ChannelLogWorkerOut(BaseModel):
    id: uuid.UUID
    name: str


class ChannelLogOut(BaseModel):
    """One message in the organization's channel log (roadmap 7.2). No message text: logs show
    what happened, not what was said."""

    id: uuid.UUID
    created_at: datetime
    direction: Literal["in", "out"]
    channel: Literal["telegram", "whatsapp"]
    kind: str
    # Outgoing only: pending, sent, uncertain (may have arrived), failed, delivered, read.
    delivery_status: str | None
    attempts: int
    # Why it failed: blocked (the worker blocked the bot), network, rejected (the channel refused
    # it), taken_over (held back while an admin answered), other. Null unless failed/uncertain.
    failure: Literal["blocked", "network", "rejected", "taken_over", "timeout", "other"] | None
    # Fluctuz will try again on its own (roadmap 7.2: three retries with backoff).
    retrying: bool
    extension_worker: ChannelLogWorkerOut | None
    # "+62 811-****-1234" or "•••6789" (Telegram chat id).
    contact: str
    conversation_id: uuid.UUID | None
