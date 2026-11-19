"""Reference data: what answers are matched against, and where a GPS point falls.

Other modules call `locate` (reports fill region_id from a report's point) and `list_items`.
"""

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import InvalidCursor
from app.modules.reference_data import errors, repository
from app.modules.reference_data.constants import MAX_GEOMETRY_LIMIT, NEAREST_DISTRICT_METERS
from app.modules.reference_data.schemas import (
    LatLng,
    ReferenceItemOut,
    RegionPathOut,
    RegionRef,
)

_LEVELS_BY_DEPTH = {1: "province", 2: "regency", 3: "district", 4: "village"}
_SEED_BATCH = 500


async def list_items(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    type_: str,
    parent_id: uuid.UUID | None = None,
    level: str | None = None,
    q: str | None = None,
    after: list[str] | None = None,
    limit: int = 20,
    with_geometry: bool = False,
) -> tuple[list[ReferenceItemOut], tuple[str, str] | None]:
    """A page of rows visible to the workspace and the cursor values of its last row when more
    follow."""
    if with_geometry and type_ != "region":
        raise errors.GeometryOnlyForRegions()
    if with_geometry and limit > MAX_GEOMETRY_LIMIT:
        raise errors.GeometryLimitTooHigh()
    if parent_id is not None and await repository.get_visible(db, workspace_id, parent_id) is None:
        raise errors.ReferenceItemNotFound()
    rows = await repository.list_items(
        db,
        workspace_id,
        type_=type_,
        parent_id=parent_id,
        level=level,
        q=q,
        after=_parse_after(after),
        limit=limit,
        with_geometry=with_geometry,
    )
    more = None
    if len(rows) > limit:
        rows = rows[:limit]
        more = (rows[-1].sort_key, str(rows[-1].id))
    return [_to_out(r, with_geometry) for r in rows], more


async def locate(db: AsyncSession, *, lat: float, lng: float) -> RegionPathOut:
    """District, regency and province of a GPS point (platform regions)."""
    found = await repository.find_region_at(
        db, lat=lat, lng=lng, level="district", nearest_meters=NEAREST_DISTRICT_METERS
    )
    if found is None:
        found = await repository.find_region_at(
            db, lat=lat, lng=lng, level="regency", nearest_meters=NEAREST_DISTRICT_METERS
        )
    path: dict[str, RegionRef | None] = {"district": None, "regency": None, "province": None}
    current = found
    while current is not None:
        if current.level in path:
            path[current.level] = RegionRef(id=current.id, code=current.code, value=current.value)
        if current.parent_id is None:
            break
        parents = await repository.get_platform_regions(db, [current.parent_id])
        current = parents[0] if parents else None
    return RegionPathOut(**path)


async def check_work_area(
    db: AsyncSession,
    province_id: uuid.UUID | None,
    regency_ids: list[uuid.UUID],
    *,
    field_prefix: str = "",
) -> None:
    """A work area is a platform province plus, optionally, some of its regencies. Raises
    UnknownRegion with the dotted path of the first bad id."""
    if province_id is None:
        if regency_ids:
            raise errors.UnknownRegion(field=f"{field_prefix}regency_ids.0")
        return
    ids = [province_id, *regency_ids]
    found = {r.id: r for r in await repository.get_platform_regions(db, ids)}
    province = found.get(province_id)
    if province is None or province.level != "province":
        raise errors.UnknownRegion(field=f"{field_prefix}province_id")
    for i, regency_id in enumerate(regency_ids):
        regency = found.get(regency_id)
        if regency is None or regency.level != "regency" or regency.parent_id != province_id:
            raise errors.UnknownRegion(field=f"{field_prefix}regency_ids.{i}")


# --- Seeding (scripts/seed.py reference) ----------------------------------------------------


async def seed_platform_regions(db: AsyncSession, features: list[dict[str, Any]]) -> int:
    """Insert or update Kemendagri regions from GeoJSON features (properties: code, name,
    centroid [lng, lat]), level by level so each parent exists before its children."""
    by_depth: dict[int, list[dict[str, Any]]] = {}
    for feature in features:
        depth = feature["properties"]["code"].count(".") + 1
        by_depth.setdefault(depth, []).append(feature)
    total = 0
    for depth in sorted(by_depth):
        level = _LEVELS_BY_DEPTH[depth]
        batch = by_depth[depth]
        parent_codes = sorted({_parent_code(f) for f in batch if depth > 1})
        parents = await repository.get_platform_ids_by_code(db, "region", parent_codes)
        rows = []
        for feature in batch:
            props = feature["properties"]
            parent = parents.get(_parent_code(feature)) if depth > 1 else None
            if depth > 1 and parent is None:
                raise ValueError(f"region {props['code']} has no parent in the data")
            lng, lat = props.get("centroid") or _first_point(feature["geometry"])
            rows.append(
                {
                    "code": props["code"],
                    "value": props["name"],
                    "level": level,
                    "parent_id": parent,
                    "lat": lat,
                    "lng": lng,
                    "geometry": feature["geometry"],
                }
            )
        for start in range(0, len(rows), _SEED_BATCH):
            await repository.upsert_platform_regions(db, rows[start : start + _SEED_BATCH])
        await db.flush()
        total += len(rows)
    await db.commit()
    return total


async def seed_platform_items(db: AsyncSession, type_: str, items: list[dict[str, Any]]) -> int:
    """Insert or update platform commodities or units (code, value, aliases)."""
    rows = [
        {
            "type": type_,
            "code": item["code"],
            "value": item["value"],
            "aliases": sorted({a.strip().lower() for a in item.get("aliases", []) if a.strip()}),
        }
        for item in items
    ]
    await repository.upsert_platform_items(db, rows)
    await db.commit()
    return len(rows)


def _parse_after(after: list[str] | None) -> tuple[str, uuid.UUID] | None:
    if after is None:
        return None
    try:
        return after[0], uuid.UUID(after[1])
    except ValueError:
        raise InvalidCursor() from None


def _parent_code(feature: dict[str, Any]) -> str:
    return feature["properties"]["code"].rsplit(".", 1)[0]


def _first_point(geometry: dict[str, Any]) -> tuple[float, float]:
    lng, lat = geometry["coordinates"][0][0][0]
    return lng, lat


def _to_out(row: Any, with_geometry: bool) -> ReferenceItemOut:
    centroid = LatLng(lat=row.lat, lng=row.lng) if row.lat is not None else None
    return ReferenceItemOut(
        id=row.id,
        type=row.type,
        code=row.code,
        value=row.value,
        aliases=list(row.aliases or []),
        parent_id=row.parent_id,
        level=row.level,
        centroid=centroid,
        geometry=json.loads(row.geojson) if with_geometry and row.geojson else None,
        source="platform" if row.workspace_id is None else "workspace",
    )
