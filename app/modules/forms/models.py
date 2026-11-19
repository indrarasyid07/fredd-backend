import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, WorkspaceOwned


class Form(UUIDPrimaryKey, Timestamps, WorkspaceOwned, Base):
    """A data structure (Struktur data). Its fields live in versions; `current_version_id` is the
    published one that new conversations use (null until the first publish)."""

    __tablename__ = "forms"
    __table_args__ = (
        CheckConstraint("status in ('draft', 'pilot', 'active', 'archived')", name="status"),
    )

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="draft")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_versions.id", ondelete="SET NULL", use_alter=True)
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Wizard choices that are not fields (FormSettings): template, sector, area, commodities,
    # reporting frequency, agent style. Validated before every write.
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class FormVersion(UUIDPrimaryKey, Timestamps, WorkspaceOwned, Base):
    """One numbered definition of a form. Editable while `published_at` is null (the draft, at most
    one per form); never changed after publishing, because reports point at it."""

    __tablename__ = "form_versions"
    __table_args__ = (
        UniqueConstraint("form_id", "version"),
        CheckConstraint("version > 0", name="version"),
        Index(
            "uq_form_versions_one_draft",
            "form_id",
            unique=True,
            postgresql_where=text("published_at is null"),
        ),
    )

    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    # FormDefinition.to_json(); validated before every write.
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class FormTemplateSector(UUIDPrimaryKey, Timestamps, Base):
    """A sector of the wizard's template catalogue (platform data, same for every workspace)."""

    __tablename__ = "form_template_sectors"

    code: Mapped[str] = mapped_column(String(40), unique=True)
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    heading: Mapped[str] = mapped_column(String(200))
    # Label and choices of the sector's quick picks ("Komoditas utama": Padi, Jagung, ...).
    chips_label: Mapped[str] = mapped_column(String(100))
    chips: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))


class FormTemplate(UUIDPrimaryKey, Timestamps, Base):
    """A starting point in the wizard. The wizard derives starter fields from `description`."""

    __tablename__ = "form_templates"

    sector_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_template_sectors.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(40), unique=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    # Suggested name of a form created from it.
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    field_count: Mapped[int] = mapped_column(Integer)
    minutes: Mapped[int] = mapped_column(Integer)
