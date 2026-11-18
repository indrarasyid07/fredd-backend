import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks

from app.api.deps import DB, AdminMember, CurrentUser
from app.api.pagination import Cursor, Limit, decode_cursor, encode_cursor
from app.api.responses import ApiErrorResponse, ApiResponse, Pagination, ok
from app.modules.members import service
from app.modules.members.schemas import (
    CreateInviteRequest,
    InviteOut,
    MemberOut,
    UpdateMemberRequest,
)

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR}


def _page(limit: int, more: tuple[object, object] | None) -> Pagination:
    next_cursor = encode_cursor(list(more)) if more else None
    return Pagination(next_cursor=next_cursor, limit=limit, has_more=more is not None)


@router.get("", response_model=ApiResponse[list[MemberOut]], responses=_GUARDS)
async def list_members(member: AdminMember, db: DB, limit: Limit = 20, cursor: Cursor = None):
    items, more = await service.list_members(
        db, member, after=decode_cursor(cursor, 2), limit=limit
    )
    return ok(items, pagination=_page(limit, more))


# Invite routes come before /{member_id} so "invites" is never read as a member id.


@router.get("/invites", response_model=ApiResponse[list[InviteOut]], responses=_GUARDS)
async def list_invites(member: AdminMember, db: DB, limit: Limit = 20, cursor: Cursor = None):
    items, more = await service.list_invites(
        db, member, after=decode_cursor(cursor, 2), limit=limit
    )
    return ok(items, pagination=_page(limit, more))


@router.post(
    "/invites", response_model=ApiResponse[InviteOut], responses={**_GUARDS, 409: _ERR, 422: _ERR}
)
async def create_invite(
    body: CreateInviteRequest,
    member: AdminMember,
    user: CurrentUser,
    db: DB,
    background: BackgroundTasks,
):
    invite = await service.invite(db, member, user, body, background)
    return ok(invite, message=f"Undangan dikirim ke {invite.email}.")


@router.post(
    "/invites/{invite_id}/resend", response_model=ApiResponse[InviteOut], responses=_GUARDS
)
async def resend_invite(
    invite_id: uuid.UUID,
    member: AdminMember,
    user: CurrentUser,
    db: DB,
    background: BackgroundTasks,
):
    invite = await service.resend_invite(db, member, user, invite_id, background)
    return ok(invite, message=f"Undangan dikirim ulang ke {invite.email}.")


@router.delete("/invites/{invite_id}", response_model=ApiResponse[None], responses=_GUARDS)
async def revoke_invite(invite_id: uuid.UUID, member: AdminMember, db: DB):
    await service.revoke_invite(db, member, invite_id)
    return ok(None, message="Undangan dibatalkan.")


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
