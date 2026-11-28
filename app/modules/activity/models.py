import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey, WorkspaceOwned

ACTIVITY_TYPES = ("report_received", "needs_help")
ACTIVITY_STATUSES = ("done", "needs_review", "needs_help")


class ActivityEvent(UUIDPrimaryKey, WorkspaceOwned, Base):
    """One thing the bot did or met in a chat. Append-only; written in the chat's transaction,
    so an event exists exactly when the change it describes does."""

    __tablename__ = "activity_events"
    __table_args__ = (
        CheckConstraint(
            "type in (" + ", ".join(f"'{t}'" for t in ACTIVITY_TYPES) + ")", name="type"
        ),
        CheckConstraint(
            "status in (" + ", ".join(f"'{s}'" for s in ACTIVITY_STATUSES) + ")", name="status"
        ),
        CheckConstraint("channel is null or channel in ('telegram', 'whatsapp')", name="channel"),
        Index("activity_events_feed_idx", "workspace_id", "occurred_at", "id"),
        Index("activity_events_conversation_idx", "conversation_id"),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    extension_worker_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extension_workers.id", ondelete="SET NULL")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    channel: Mapped[str | None] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    # By type: report_received {report_id, code, form_name}; needs_help {reason, field, form_name}.
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
