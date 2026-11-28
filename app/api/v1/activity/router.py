"""Aktivitas Agent log of the active workspace, newest first (reviewer and up, roadmap 6.2)."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import DB, ReviewerMember
from app.api.pagination import Cursor, Limit, decode_cursor, encode_cursor
from app.api.responses import ApiErrorResponse, ApiResponse, Pagination, ok
from app.modules.activity import service
from app.modules.activity.schemas import ActivityEventOut, ActivityType

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR}


@router.get("", response_model=ApiResponse[list[ActivityEventOut]], responses=_GUARDS)
async def list_activity(
    member: ReviewerMember,
    db: DB,
    type: ActivityType | None = None,
    limit: Limit = 20,
    cursor: Cursor = None,
):
    items, more = await service.list_events(
        db, member, type=type, after=decode_cursor(cursor, 2), limit=limit
    )
    next_cursor = encode_cursor(list(more)) if more else None
    return ok(
        items,
        pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=more is not None),
    )
