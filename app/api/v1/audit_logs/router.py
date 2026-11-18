"""Audit log of the active workspace, newest first (admin). Served by the members module (B-055)."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import DB, AdminMember
from app.api.pagination import Cursor, Limit, decode_cursor, encode_cursor
from app.api.responses import ApiErrorResponse, ApiResponse, Pagination, ok
from app.modules.members import service
from app.modules.members.schemas import AuditLogOut

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR}


@router.get("", response_model=ApiResponse[list[AuditLogOut]], responses=_GUARDS)
async def list_audit_logs(member: AdminMember, db: DB, limit: Limit = 20, cursor: Cursor = None):
    items, more = await service.list_audit_logs(
        db, member, after=decode_cursor(cursor, 2), limit=limit
    )
    next_cursor = encode_cursor(list(more)) if more else None
    return ok(
        items,
        pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=more is not None),
    )
