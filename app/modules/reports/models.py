import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, WorkspaceOwned


class Report(UUIDPrimaryKey, Timestamps, WorkspaceOwned, Base):
    """One field report (Laporan). `answers` keeps every answer as the chat stored it; the filter
    columns are copied from it once, at creation, so the dashboard never parses JSON."""

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("workspace_id", "code"),
        CheckConstraint(
            "condition is null or condition in ('healthy', 'attention', 'infected')",
            name="condition",
        ),
        Index("ix_reports_workspace_received", "workspace_id", text("received_at desc")),
        Index(
            "ix_reports_workspace_region_received",
            "workspace_id",
            "region_id",
            text("received_at desc"),
        ),
        Index(
            "ix_reports_workspace_condition_received",
            "workspace_id",
            "condition",
            text("received_at desc"),
        ),
        Index(
            "ix_reports_workspace_plot_received",
            "workspace_id",
            "plot_key",
            text("received_at desc"),
        ),
        Index("ix_reports_worker_received", "extension_worker_id", text("received_at desc")),
    )

    # LP-YYMM-NNNN, per workspace and month (B-XXX).
    code: Mapped[str] = mapped_column(String(20))
    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id", ondelete="RESTRICT"))
    form_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_versions.id", ondelete="RESTRICT")
    )
    extension_worker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extension_workers.id", ondelete="RESTRICT")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    # Most specific platform region of the point (district, else regency).
    region_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reference_data.id", ondelete="SET NULL")
    )
    # No field role points at a commodity yet; stays null until one does.
    commodity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reference_data.id", ondelete="SET NULL")
    )
    condition: Mapped[str | None] = mapped_column(String(16))
    area_ha: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    # 50 m grid cell + worker + structure, for "unique plots" (dashboard.md).
    plot_key: Mapped[str | None] = mapped_column(String(64))
    complete: Mapped[bool] = mapped_column(Boolean)
    needs_review: Mapped[bool] = mapped_column(Boolean, server_default="false")
    review_reasons: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Voice Lab (roadmap 12.3): the sentence that filled the report: transcript, audio object
    # key, and per field the words heard and the confidence. Null for chat reports.
    voice: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ReportPhoto(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "report_photos"

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    # Which field the file answered, and its place in that answer.
    field_key: Mapped[str] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer)
    # Storage reference from the chat (final storage arrives with roadmap 5.1).
    object_key: Mapped[str] = mapped_column(String(300))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    blur_score: Mapped[float | None] = mapped_column(Float)
    ai_note: Mapped[str | None] = mapped_column(String(500))


class ReportCodeCounter(Base):
    """The last number handed out per workspace and month. Taken with one atomic upsert, so two
    reports at the same moment never share a code (never "largest + 1")."""

    __tablename__ = "report_code_counters"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    # YYMM in the workspace's time zone.
    period: Mapped[str] = mapped_column(String(4), primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer)


class ReportValue(UUIDPrimaryKey, WorkspaceOwned, Base):
    """One choice or number answer of a report, copied at creation (D17) so dashboard widgets
    aggregate any field with plain SQL, never by parsing `answers`. A multiple choice answer is
    one row per chosen value. `received_at` repeats the report's, for range filters."""

    __tablename__ = "report_values"
    __table_args__ = (
        CheckConstraint("(choice is null) <> (number is null)", name="one_value"),
        Index(
            "ix_report_values_field_received",
            "workspace_id",
            "form_id",
            "field_key",
            text("received_at desc"),
        ),
    )

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    field_key: Mapped[str] = mapped_column(String(64))
    choice: Mapped[str | None] = mapped_column(String(200))
    number: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
