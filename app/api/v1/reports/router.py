"""Field reports of the active workspace (roadmap 4.3): list and detail, for reviewers up."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import DB, ReviewerMember
from app.api.pagination import Cursor, Limit, decode_cursor, encode_cursor
from app.api.responses import ApiErrorResponse, ApiResponse, Pagination, ok
from app.modules.reports import service
from app.modules.reports.schemas import (
    ConditionFilter,
    CorrectValueRequest,
    ReportDetailOut,
    ReportListItemOut,
)

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR}


@router.get("", response_model=ApiResponse[list[ReportListItemOut]], responses=_GUARDS)
async def list_reports(
    member: ReviewerMember,
    db: DB,
    form_id: uuid.UUID | None = None,
    extension_worker_id: uuid.UUID | None = None,
    region_id: uuid.UUID | None = None,
    condition: Annotated[
        list[ConditionFilter] | None,
        Query(description="Saring kondisi (boleh lebih dari satu); `unknown` = tanpa kondisi."),
    ] = None,
    needs_review: bool | None = None,
    verified: bool | None = None,
    voice: Annotated[
        bool | None, Query(description="true: hanya laporan dari pesan suara (Voice Lab).")
    ] = None,
    since: Annotated[datetime | None, Query(description="Diterima sejak (inklusif).")] = None,
    until: Annotated[datetime | None, Query(description="Diterima sebelum (eksklusif).")] = None,
    limit: Limit = 20,
    cursor: Cursor = None,
):
    items, more = await service.list_reports(
        db,
        member.workspace_id,
        form_id=form_id,
        extension_worker_id=extension_worker_id,
        region_id=region_id,
        conditions=list(condition) if condition else None,
        needs_review=needs_review,
        verified=verified,
        voice=voice,
        since=since,
        until=until,
        after=decode_cursor(cursor, 2),
        limit=limit,
    )
    next_cursor = encode_cursor(more) if more else None
    return ok(
        items,
        pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=more is not None),
    )


@router.get("/{report_id}", response_model=ApiResponse[ReportDetailOut], responses=_GUARDS)
async def get_report(report_id: uuid.UUID, member: ReviewerMember, db: DB):
    return ok(await service.get_report_detail(db, member.workspace_id, report_id))


@router.post(
    "/{report_id}/corrections",
    response_model=ApiResponse[ReportDetailOut],
    responses={**_GUARDS, 409: _ERR, 422: _ERR},
)
async def correct_report_value(
    report_id: uuid.UUID, body: CorrectValueRequest, member: ReviewerMember, db: DB
):
    """Replace one value with a reason (roadmap 12.5). Refused once the report is verified."""
    detail = await service.correct_value(
        db, member.workspace_id, report_id, member.member.user_id, body
    )
    return ok(detail, message="Nilai dikoreksi dan dicatat di jejak audit.")


@router.post(
    "/{report_id}/verify",
    response_model=ApiResponse[ReportDetailOut],
    responses={**_GUARDS, 409: _ERR},
)
async def verify_report(report_id: uuid.UUID, member: ReviewerMember, db: DB):
    """A supervisor confirms the values; corrections are no longer possible (roadmap 12.5)."""
    detail = await service.verify_report(db, member.workspace_id, report_id, member.member.user_id)
    return ok(detail, message="Laporan diverifikasi.")
