import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, WorkspaceOwned

CONVERSATION_STATUSES = (
    "idle",
    "joining",
    "identifying",
    "choosing_form",
    "asking",
    "confirming_summary",
    "submitted",
    "needs_help",
    "taken_over",
)


class Conversation(UUIDPrimaryKey, Timestamps, WorkspaceOwned, Base):
    """One worker's chat about one topic. Reports are filled one after another in the same
    conversation; `state` is the engine's ConversationState (engine/types.py)."""

    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "status in (" + ", ".join(f"'{s}'" for s in CONVERSATION_STATUSES) + ")",
            name="status",
        ),
        UniqueConstraint("extension_worker_id", "form_id"),
        # Due reminders (roadmap 7.1).
        Index(
            "conversations_next_reminder_idx",
            "next_reminder_at",
            postgresql_where=text("next_reminder_at is not null"),
        ),
    )

    extension_worker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extension_workers.id", ondelete="CASCADE"), index=True
    )
    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    # The published version the current report follows; fixed until it is submitted.
    form_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_versions.id", ondelete="SET NULL")
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    chat_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), server_default="idle")
    # Key of the field being asked (mirrors state["step"] for queries and the dashboard).
    step: Mapped[str | None] = mapped_column(String(50))
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    failed_attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    # Last message from the worker: WhatsApp's 24-hour window and reminders.
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    taken_over_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    taken_over_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(UUIDPrimaryKey, Base):
    """Every message in and out, kept before it is processed so none is lost.

    A message from a chat not bound to any organization keeps `workspace_id` and
    `conversation_id` null: it never creates data in an organization (tenant isolation).
    Outgoing: `pending` before the API call, `sent` after, `uncertain` on a timeout (never sent
    twice blindly), `failed` after retries; WhatsApp may add `delivered`/`read`."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("direction in ('in', 'out')", name="direction"),
        CheckConstraint(
            "kind in ('text', 'button', 'location', 'photo', 'video', 'voice', 'document', "
            "'other')",
            name="kind",
        ),
        CheckConstraint(
            "delivery_status is null or delivery_status in "
            "('pending', 'sent', 'uncertain', 'failed', 'delivered', 'read')",
            name="delivery_status",
        ),
        # Webhooks repeat; the same update is stored once.
        UniqueConstraint("channel_id", "direction", "external_id"),
        # Failed sends waiting to be tried again (roadmap 7.2).
        Index("messages_retry_idx", "retry_at", postgresql_where=text("retry_at is not null")),
        # Unprocessed inbound messages per chat, oldest first (worker and the sweep job).
        Index(
            "messages_unprocessed_idx",
            "channel_id",
            "chat_id",
            "channel_sent_at",
            postgresql_where=text("direction = 'in' and processed_at is null"),
        ),
        Index("messages_conversation_idx", "conversation_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    chat_id: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(3))
    kind: Mapped[str] = mapped_column(String(16))
    # Text typed or sent; button value; null for media without caption.
    body: Mapped[str | None] = mapped_column(Text)
    # Channel details the engine needs (location, media file id, buttons offered...).
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    # Where the media was copied to (object storage key).
    media_key: Mapped[str | None] = mapped_column(String(300))
    # The channel's id: Telegram update/message id, WhatsApp wamid. Null for outbound until sent.
    external_id: Mapped[str | None] = mapped_column(String(128))
    # When the channel says the message was sent; orders a chat's messages.
    channel_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_status: Mapped[str | None] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str | None] = mapped_column(String(300))
    # A failed send that may be tried again, and when (roadmap 7.2); null = not retried.
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
