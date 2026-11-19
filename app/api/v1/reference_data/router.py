"""Reference data visible to the active workspace: platform rows (Kemendagri regions, standard
commodities and units) plus the workspace's own. Any member may read."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import DB, ReviewerMember
from app.api.pagination import Cursor, Limit, decode_cursor, encode_cursor
from app.api.responses import ApiErrorResponse, ApiResponse, Pagination, ok
from app.modules.reference_data import service
from app.modules.reference_data.constants import ReferenceType, RegionLevel
from app.modules.reference_data.schemas import ReferenceItemOut, RegionPathOut

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR, 422: _ERR}


@router.get("", response_model=ApiResponse[list[ReferenceItemOut]], responses=_GUARDS)
async def list_reference_data(
    member: ReviewerMember,
    db: DB,
    type: Annotated[ReferenceType, Query(description="Jenis data rujukan.")],
    parent_id: Annotated[uuid.UUID | None, Query(description="Anak dari baris ini.")] = None,
    level: Annotated[RegionLevel | None, Query(description="Tingkat wilayah.")] = None,
    q: Annotated[
        str | None, Query(min_length=2, max_length=100, description="Cari nama/alias.")
    ] = None,
    geometry: Annotated[
        bool, Query(description="Sertakan batas wilayah (GeoJSON), maks. 50 baris.")
    ] = False,
    limit: Limit = 20,
    cursor: Cursor = None,
):
    items, more = await service.list_items(
        db,
        member.workspace.id,
        type_=type,
        parent_id=parent_id,
        level=level,
        q=q,
        after=decode_cursor(cursor, 2),
        limit=limit,
        with_geometry=geometry,
    )
    next_cursor = encode_cursor(list(more)) if more else None
    return ok(
        items,
        pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=more is not None),
    )


@router.get("/locate", response_model=ApiResponse[RegionPathOut], responses=_GUARDS)
async def locate_point(
    _: ReviewerMember,
    db: DB,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
):
    return ok(await service.locate(db, lat=lat, lng=lng))
