import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey


class Channel(UUIDPrimaryKey, Timestamps, Base):
    """A bot extension workers chat with. `workspace_id` null = the platform's shared bot (B-048):
    one Telegram bot and one WhatsApp number for every organization. Credentials live in the
    environment, never here."""

    __tablename__ = "channels"
    __table_args__ = (
        CheckConstraint("type in ('telegram', 'whatsapp')", name="type"),
        CheckConstraint("status in ('active', 'disabled')", name="status"),
        Index(
            "uq_channels_platform_type",
            "type",
            unique=True,
            postgresql_where=text("workspace_id is null"),
        ),
    )

    # Kept for a later "own bot" option (Enterprise); null today.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    display_name: Mapped[str] = mapped_column(String(100))
    # Telegram: the bot's username without @. WhatsApp: the Cloud API phone number id.
    bot_username: Mapped[str | None] = mapped_column(String(64))
    phone_number_id: Mapped[str | None] = mapped_column(String(64))
