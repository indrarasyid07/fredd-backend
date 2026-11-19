import uuid
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey


class ReferenceData(UUIDPrimaryKey, Timestamps, Base):
    """Regions, commodities, farmer groups and units that answers are matched against.

    `workspace_id` null = platform data every workspace sees (regions from Kemendagri, the
    standard commodity and unit lists); a workspace may add its own rows. Regions form a tree
    through `parent_id` and carry a centroid and a boundary, so a GPS point can be placed in
    its district (B-XXX).
    """

    __tablename__ = "reference_data"
    __table_args__ = (
        CheckConstraint("type in ('region', 'commodity', 'farmer_group', 'unit')", name="type"),
        CheckConstraint("(type = 'region') = (level is not null)", name="region_level"),
        CheckConstraint(
            "level is null or level in ('province', 'regency', 'district', 'village')",
            name="level",
        ),
        # One platform row per code and type; workspaces may reuse codes for their own rows.
        Index(
            "uq_reference_data_platform_code",
            "type",
            "code",
            unique=True,
            postgresql_where=text("workspace_id is null"),
        ),
        Index("reference_data_type_parent_idx", "type", "parent_id"),
        Index("reference_data_workspace_type_idx", "workspace_id", "type"),
        # Point-in-polygon lookups (ST_Covers, &&, <->).
        Index("reference_data_boundary_idx", "boundary", postgresql_using="gist"),
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(16))
    # Stable key: Kemendagri code for regions ("32.01"), English key for commodities ("rice").
    code: Mapped[str | None] = mapped_column(String(40))
    # Display name in Indonesian ("Kabupaten Bogor", "Padi").
    value: Mapped[str] = mapped_column(String(200))
    # Other words people use for it, lowercase ("pari", "gabah"; "hektar").
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), server_default=text("'{}'::varchar[]")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reference_data.id", ondelete="CASCADE")
    )
    level: Mapped[str | None] = mapped_column(String(16))
    centroid: Mapped[Any | None] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False))
    boundary: Mapped[Any | None] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=False)
    )
