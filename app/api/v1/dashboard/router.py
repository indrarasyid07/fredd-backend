"""The dashboard's numbers (roadmap 4.2) and generic widget data per structure (4.7), for
reviewers up."""

import uuid
from typing import Any

from fastapi import APIRouter

from app.api.deps import DB, ReviewerMember
from app.api.responses import ApiErrorResponse, ApiResponse, ok
from app.modules.dashboard import service
from app.modules.dashboard.schemas import DashboardRange, DashboardSummaryOut, FormDashboardOut

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
