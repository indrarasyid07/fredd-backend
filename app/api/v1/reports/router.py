"""Field reports of the active workspace (roadmap 4.3): list and detail, for reviewers up."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.api.deps import DB, EditorMember, ReviewerMember
from app.api.pagination import Cursor, Limit, decode_cursor, encode_cursor
from app.api.responses import ApiErrorResponse, ApiResponse, Pagination, ok
from app.modules.reports import service
from app.modules.reports.exports import MEDIA_TYPES, ExportFormat
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
    q: Annotated[
        str | None,
        Query(max_length=100, description="Cari kode laporan, nama penyuluh, atau nama wilayah."),
    ] = None,
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
        q=q,
    )
    next_cursor = encode_cursor(more) if more else None
    return ok(
        items,
        pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=more is not None),
    )


_FILE = {"schema": {"type": "string", "format": "binary"}}


@router.get(
    "/voice-export",
    response_class=Response,
    responses={
        200: {
            "description": "Berkas CSV atau Excel.",
            "content": {MEDIA_TYPES["csv"]: _FILE, MEDIA_TYPES["xlsx"]: _FILE},
        },
        **_GUARDS,
        422: _ERR,
    },
)
async def export_voice_reports(
    member: EditorMember,
    db: DB,
    form_id: uuid.UUID,
    format: Annotated[ExportFormat, Query(description="`csv` atau `xlsx`.")] = "csv",  # noqa: A002
    since: Annotated[datetime | None, Query(description="Diterima sejak (inklusif).")] = None,
    until: Annotated[datetime | None, Query(description="Diterima sebelum (eksklusif).")] = None,
) -> Response:
    """Verified Voice Lab results of one structure as a file (roadmap 12.6), at most 5.000
    rows; errors before the file use the standard JSON format."""
    file = await service.export_voice(
        db,
        member.workspace_id,
        member.member.user_id,
        form_id=form_id,
        fmt=format,
        since=since,
        until=until,
    )
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={"Content-Disposition": f'attachment; filename="{file.filename}"'},
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
