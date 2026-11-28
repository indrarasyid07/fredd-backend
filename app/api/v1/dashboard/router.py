"""The dashboard's numbers (roadmap 4.2) and generic widget data per structure (4.7), for
reviewers up."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response

from app.api.deps import DB, ReviewerMember
from app.api.responses import ApiErrorResponse, ApiResponse, ok
from app.modules.dashboard import map as report_map
from app.modules.dashboard import service
from app.modules.dashboard.schemas import (
    BoundariesOut,
    DashboardRange,
    DashboardSummaryOut,
    FormDashboardOut,
    ReportMapOut,
)

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {401: _ERR, 403: _ERR, 422: _ERR}


@router.get("/summary", response_model=ApiResponse[DashboardSummaryOut], responses=_GUARDS)
async def dashboard_summary(member: ReviewerMember, db: DB, range: DashboardRange = "today"):  # noqa: A002
    return ok(await service.summary(db, member.workspace_id, range))


@router.get(
    "/forms/{form_id}",
    response_model=ApiResponse[FormDashboardOut],
    responses={**_GUARDS, 404: _ERR},
)
async def form_dashboard(
    form_id: uuid.UUID,
    member: ReviewerMember,
    db: DB,
    range: DashboardRange = "today",  # noqa: A002
):
    """Generic widget data for one structure: totals, 7-day trend, every choice and number
    field, top regencies (roadmap 4.7)."""
    return ok(await service.form_dashboard(db, member.workspace_id, form_id, range))


@router.get("/map", response_model=ApiResponse[ReportMapOut], responses={**_GUARDS, 404: _ERR})
async def dashboard_map(
    member: ReviewerMember,
    db: DB,
    range: DashboardRange = "today",  # noqa: A002
    form_id: uuid.UUID | None = None,
    color_by: Annotated[
        str | None,
        Query(max_length=64, description="Kunci isian pilihan tunggal yang mewarnai peta."),
    ] = None,
    value: Annotated[
        list[str] | None,
        Query(description="Hanya nilai ini (boleh berulang; `unknown` = tanpa jawaban)."),
    ] = None,
):
    """Regencies and the newest located reports for the map (roadmap 5.2). Without `form_id`
    the crop condition colours it; with one, its condition, `color_by`, its `status` field or
    its first single choice. Health structures send regions only (≥ 5 reports)."""
    data = await report_map.report_map(
        db,
        member.workspace_id,
        range_=range,
        form_id=form_id,
        color_by=color_by,
        values=[v[:200] for v in (value or [])][:20],
    )
    return ok(data)


@router.get("/boundaries", response_model=ApiResponse[BoundariesOut], responses=_GUARDS)
async def region_boundaries(
    member: ReviewerMember,
    db: DB,
    response: Response,
    id: Annotated[list[uuid.UUID], Query(description="Wilayah (maks. 100).")],  # noqa: A002
):
    """Simplified outlines of regions for the map's region layer; platform data, cached a day."""
    response.headers["Cache-Control"] = "private, max-age=86400"
    return ok(await report_map.region_boundaries(db, id))
