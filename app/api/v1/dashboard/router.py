"""The dashboard's numbers (roadmap 4.2), for reviewers up."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import DB, ReviewerMember
from app.api.responses import ApiErrorResponse, ApiResponse, ok
from app.modules.dashboard import service
from app.modules.dashboard.schemas import DashboardRange, DashboardSummaryOut

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {401: _ERR, 403: _ERR, 422: _ERR}


@router.get("/summary", response_model=ApiResponse[DashboardSummaryOut], responses=_GUARDS)
async def dashboard_summary(member: ReviewerMember, db: DB, range: DashboardRange = "today"):  # noqa: A002
    return ok(await service.summary(db, member.workspace_id, range))
