import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.modules.workspaces.constants import (
    DEFAULT_RETENTION_CONVERSATIONS_MONTHS,
    DEFAULT_RETENTION_PHOTOS_MONTHS,
    DEFAULT_TIMEZONE,
)


class Workspace(UUIDPrimaryKey, Timestamps, Base):
    """A tenant. Every tenant-owned row carries its id as `workspace_id`."""

    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("type in ('personal', 'organization')", name="type"),
        # A personal workspace always has exactly one owner; an organization never does (B-049).
        CheckConstraint(
            "(type = 'personal') = (personal_owner_id is not null)", name="personal_owner"
        ),
        CheckConstraint("retention_conversations_months > 0", name="retention_conversations"),
        CheckConstraint("retention_photos_months > 0", name="retention_photos"),
    )

    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(16))
    # Unique: at most one personal workspace per user, while organizations are unlimited (D13).
    personal_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    timezone: Mapped[str] = mapped_column(String(64), server_default=DEFAULT_TIMEZONE)
    # {"days": [1..7], "start": "07:00", "end": "17:00"}; null = no limit.
    operating_hours: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # {"start": "21:00", "end": "06:00"}; null = reminders may go out any time.
    quiet_hours: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    retention_conversations_months: Mapped[int] = mapped_column(
        Integer, server_default=str(DEFAULT_RETENTION_CONVERSATIONS_MONTHS)
    )
    retention_photos_months: Mapped[int] = mapped_column(
        Integer, server_default=str(DEFAULT_RETENTION_PHOTOS_MONTHS)
    )
    require_sso: Mapped[bool] = mapped_column(Boolean, server_default=false())
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class Member(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "members"
    __table_args__ = (
        CheckConstraint("role in ('admin', 'form_editor', 'reviewer')", name="role"),
        UniqueConstraint("workspace_id", "user_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    # null = invited/requested but not yet approved; such members get no access.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
