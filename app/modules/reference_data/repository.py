import json
import uuid
from collections.abc import Sequence
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import String, any_, cast, func, literal, or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reference_data.models import ReferenceData

_R = ReferenceData


def _visible(workspace_id: uuid.UUID):  # noqa: ANN202
    """Platform rows plus the workspace's own rows."""
    return or_(_R.workspace_id.is_(None), _R.workspace_id == workspace_id)


def _sort_key(type_: str):  # noqa: ANN202
    # Regions read best in Kemendagri order; everything else alphabetically.
    return _R.code if type_ == "region" else _R.value


async def list_items(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    type_: str,
    parent_id: uuid.UUID | None,
    level: str | None,
    q: str | None,
    after: tuple[str, uuid.UUID] | None,
    limit: int,
    with_geometry: bool,
) -> Sequence[Any]:
    key = _sort_key(type_)
    columns = [
        _R.id,
        _R.workspace_id,
        _R.type,
        _R.code,
        _R.value,
        _R.aliases,
        _R.parent_id,
        _R.level,
        func.ST_Y(_R.centroid).label("lat"),
        func.ST_X(_R.centroid).label("lng"),
        (func.ST_AsGeoJSON(_R.boundary, 5) if with_geometry else literal(None)).label("geojson"),
        cast(key, String).label("sort_key"),
    ]
    query = select(*columns).where(_visible(workspace_id), _R.type == type_)
    if parent_id is not None:
        query = query.where(_R.parent_id == parent_id)
    if level is not None:
        query = query.where(_R.level == level)
    if q:
        term = q.strip().lower()
        query = query.where(
            or_(
                _R.value.ilike(f"%{_escape_like(term)}%", escape="\\"),
                literal(term) == any_(_R.aliases),
            )
        )
    if after is not None:
        query = query.where(
            tuple_(key, _R.id) > tuple_(literal(after[0], String), literal(after[1]))
        )
    query = query.order_by(key, _R.id).limit(limit + 1)
    return (await db.execute(query)).all()


async def get_visible(
    db: AsyncSession, workspace_id: uuid.UUID, item_id: uuid.UUID
) -> ReferenceData | None:
    return await db.scalar(select(_R).where(_R.id == item_id, _visible(workspace_id)))


async def get_platform_regions(db: AsyncSession, ids: Sequence[uuid.UUID]) -> list[ReferenceData]:
    query = select(_R).where(_R.id.in_(ids), _R.type == "region", _R.workspace_id.is_(None))
    return list(await db.scalars(query))


async def find_region_at(
    db: AsyncSession, *, lat: float, lng: float, level: str, nearest_meters: float
) -> ReferenceData | None:
    """The platform region of `level` covering the point, else the nearest one within
    `nearest_meters` (simplified boundaries leave gaps along coasts and borders)."""
    point = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
    base = select(_R).where(_R.type == "region", _R.workspace_id.is_(None), _R.level == level)
    covering = await db.scalar(
        base.where(_R.boundary.op("&&")(point), func.ST_Covers(_R.boundary, point)).limit(1)
    )
    if covering is not None:
        return covering
    # Index-friendly box first (a degree is at least ~110 km, so this margin covers the
    # distance), then the exact distance in meters.
    box = func.ST_Expand(point, nearest_meters / 100_000)
    near = func.ST_DWithin(cast(_R.boundary, Geography), cast(point, Geography), nearest_meters)
    query = (
        base.where(_R.boundary.op("&&")(box), near).order_by(_R.boundary.op("<->")(point)).limit(1)
    )
    return await db.scalar(query)


async def get_platform_ids_by_code(
    db: AsyncSession, type_: str, codes: Sequence[str]
) -> dict[str, uuid.UUID]:
    query = select(_R.code, _R.id).where(
        _R.workspace_id.is_(None), _R.type == type_, _R.code.in_(codes)
    )
    return {code: id_ for code, id_ in (await db.execute(query)).all() if code is not None}


_UPSERT_REGION = text(
    """
    insert into reference_data
        (id, workspace_id, type, code, value, level, parent_id, centroid, boundary)
    values (
        :id, null, 'region', :code, :value, :level, :parent_id,
        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
        ST_Multi(ST_CollectionExtract(ST_MakeValid(
            ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)), 3))
    )
    on conflict (type, code) where workspace_id is null do update set
        value = excluded.value, level = excluded.level, parent_id = excluded.parent_id,
        centroid = excluded.centroid, boundary = excluded.boundary, updated_at = now()
    """
)

_UPSERT_ITEM = text(
    """
    insert into reference_data (id, workspace_id, type, code, value, aliases)
    values (:id, null, :type, :code, :value, :aliases)
    on conflict (type, code) where workspace_id is null do update set
        value = excluded.value, aliases = excluded.aliases, updated_at = now()
    """
)


async def upsert_platform_regions(db: AsyncSession, rows: list[dict[str, Any]]) -> None:
    """Rows: code, value, level, parent_id, lat, lng, geometry (GeoJSON dict)."""
    params = [{**row, "id": uuid.uuid7(), "geometry": json.dumps(row["geometry"])} for row in rows]
    if params:
        await db.execute(_UPSERT_REGION, params)


async def upsert_platform_items(db: AsyncSession, rows: list[dict[str, Any]]) -> None:
    """Rows: type, code, value, aliases."""
    params = [{**row, "id": uuid.uuid7()} for row in rows]
    if params:
        await db.execute(_UPSERT_ITEM, params)


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
