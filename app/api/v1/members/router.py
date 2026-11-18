import uuid
from typing import Any

from fastapi import APIRouter

from app.api.deps import DB, AdminMember
from app.api.pagination import Cursor, Limit, decode_cursor, encode_cursor
from app.api.responses import ApiErrorResponse, ApiResponse, Pagination, ok
from app.modules.members import service
from app.modules.members.schemas import MemberOut, UpdateMemberRequest

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR}


@router.get("", response_model=ApiResponse[list[MemberOut]], responses=_GUARDS)
async def list_members(member: AdminMember, db: DB, limit: Limit = 20, cursor: Cursor = None):
    items, more = await service.list_members(
        db, member, after=decode_cursor(cursor, 2), limit=limit
    )
    next_cursor = encode_cursor(list(more)) if more else None
    return ok(
        items,
        pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=more is not None),
    )


@router.patch(
    "/{member_id}", response_model=ApiResponse[None], responses={**_GUARDS, 409: _ERR, 422: _ERR}
)
async def update_member(
    member_id: uuid.UUID, body: UpdateMemberRequest, member: AdminMember, db: DB
):
    await service.change_role(db, member, member_id, body.role)
    return ok(None, message="Peran anggota diperbarui.")


@router.delete("/{member_id}", response_model=ApiResponse[None], responses={**_GUARDS, 409: _ERR})
async def remove_member(member_id: uuid.UUID, member: AdminMember, db: DB):
    await service.remove(db, member, member_id)
    return ok(None, message="Anggota dikeluarkan dari workspace.")
