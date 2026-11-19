import uuid
from typing import Any, Literal

from pydantic import BaseModel

from app.modules.reference_data.constants import ReferenceType, RegionLevel


class LatLng(BaseModel):
    lat: float
    lng: float


class ReferenceItemOut(BaseModel):
    id: uuid.UUID
    type: ReferenceType
    code: str | None
    value: str
    aliases: list[str]
    parent_id: uuid.UUID | None
    # Regions only.
    level: RegionLevel | None
    centroid: LatLng | None
    # GeoJSON MultiPolygon ([lng, lat] pairs), only when asked with `geometry=true`.
    geometry: dict[str, Any] | None = None
    # "platform" rows are shared by every workspace; "workspace" rows belong to this one.
    source: Literal["platform", "workspace"]


class RegionRef(BaseModel):
    id: uuid.UUID
    code: str | None
    value: str


class RegionPathOut(BaseModel):
    """Where a GPS point falls. Fields are null when the point is outside every boundary."""

    district: RegionRef | None
    regency: RegionRef | None
    province: RegionRef | None
