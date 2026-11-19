import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, WorkspaceOwned


class JoinCode(UUIDPrimaryKey, Timestamps, WorkspaceOwned, Base):
    """The code extension workers send to the shared bot to join one data structure (B-048).
    Created with the structure; usable only once it is pilot or active."""

    __tablename__ = "join_codes"
    __table_args__ = (
        CheckConstraint("status in ('active', 'paused', 'revoked')", name="status"),
        CheckConstraint("approval_mode in ('auto', 'manual')", name="approval_mode"),
        CheckConstraint("max_uses is null or max_uses > 0", name="max_uses"),
        CheckConstraint("use_count >= 0", name="use_count"),
        # One usable (not revoked) code per structure.
        Index(
            "uq_join_codes_one_live_per_form",
            "form_id",
            unique=True,
            postgresql_where=text("status <> 'revoked'"),
        ),
    )

    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    # Stored uppercase without the dash (K7M29QXA); shown as K7M2-9QXA.
    code: Mapped[str] = mapped_column(String(16), unique=True)
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    approval_mode: Mapped[str] = mapped_column(String(16), server_default="auto")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int | None] = mapped_column(Integer)
    use_count: Mapped[int] = mapped_column(Integer, server_default="0")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
