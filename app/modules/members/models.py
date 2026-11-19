import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKey


class MemberInvite(UUIDPrimaryKey, Base):
    """An email invitation to join a workspace (B-055). Only the link token's hash is stored.

    "Open" = not accepted and not revoked. A workspace keeps at most one open invite per email;
    inviting the same address again reissues it (new link, new role, new expiry).
    """

    __tablename__ = "member_invites"
    __table_args__ = (
        CheckConstraint("role in ('admin', 'form_editor', 'reviewer')", name="role"),
        Index(
            "uq_member_invites_open_email",
            "workspace_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at is null and revoked_at is null"),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(320))  # always lowercase
    role: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
