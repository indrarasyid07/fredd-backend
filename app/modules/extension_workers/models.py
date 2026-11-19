import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, WorkspaceOwned


class ExtensionWorker(UUIDPrimaryKey, Timestamps, WorkspaceOwned, Base):
    """One person in one organization (join-codes.md "Satu orang, banyak topik"): created when
    a chat identity claims a join code. The same phone or Telegram account in two organizations
    is two rows."""

    __tablename__ = "extension_workers"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending_approval', 'active', 'left', 'blocked', 'unreachable')",
            name="status",
        ),
        CheckConstraint("name_source in ('channel_profile', 'admin')", name="name_source"),
        CheckConstraint(
            "phone_e164 is not null or telegram_user_id is not null", name="has_identity"
        ),
        Index(
            "uq_extension_workers_phone",
            "workspace_id",
            "phone_e164",
            unique=True,
            postgresql_where=text("phone_e164 is not null"),
        ),
        Index(
            "uq_extension_workers_telegram",
            "workspace_id",
            "telegram_user_id",
            unique=True,
            postgresql_where=text("telegram_user_id is not null"),
        ),
    )

    name: Mapped[str] = mapped_column(String(200))
    # Where the name came from: the chat profile at first contact, or an admin's edit.
    name_source: Mapped[str] = mapped_column(String(20), server_default="channel_profile")
    region_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reference_data.id", ondelete="SET NULL")
    )
    phone_e164: Mapped[str | None] = mapped_column(String(20))
    telegram_user_id: Mapped[str | None] = mapped_column(String(32))
    telegram_username: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), server_default="active")
    # Why a claim waits for an admin: "manual" approval or the plan's worker "quota".
    pending_reason: Mapped[str | None] = mapped_column(String(20))
    joined_via_code_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("join_codes.id", ondelete="SET NULL")
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The worker answered "Ya, tetap" to the binding question; reports need it.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FormAssignment(UUIDPrimaryKey, Timestamps, WorkspaceOwned, Base):
    """A worker's topic: the structure they report on. Bound to the form, not a version, so
    publishing a new version keeps everyone on it."""

    __tablename__ = "form_assignments"
    __table_args__ = (
        CheckConstraint("status in ('active', 'left')", name="status"),
        UniqueConstraint("extension_worker_id", "form_id"),
    )

    extension_worker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extension_workers.id", ondelete="CASCADE"), index=True
    )
    form_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forms.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    joined_via_code_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("join_codes.id", ondelete="SET NULL")
    )
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatContext(UUIDPrimaryKey, Timestamps, Base):
    """Routing for one chat identity on one bot: which topic its next message belongs to.
    Platform-level on purpose (an identity may belong to several organizations); it holds no
    content, only the pointer."""

    __tablename__ = "chat_contexts"
    __table_args__ = (UniqueConstraint("channel_id", "chat_id"),)

    channel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    # Telegram chat id or WhatsApp phone (E.164), as text.
    chat_id: Mapped[str] = mapped_column(String(64))
    active_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_assignments.id", ondelete="SET NULL")
    )
