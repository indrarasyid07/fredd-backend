"""The invite link (/invite/[token] in the web app): read it signed out, accept it signed in.

The token travels in the body, not the path, so it stays out of access logs."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import DB, CurrentUser
from app.api.responses import ApiErrorResponse, ApiResponse, ok
from app.modules.members import service
from app.modules.members.schemas import AcceptedInvite, InvitePreview, InviteTokenRequest

router = APIRouter()

_ERR = {"model": ApiErrorResponse}


@router.post(
    "/preview", response_model=ApiResponse[InvitePreview], responses={404: _ERR, 422: _ERR}
)
async def preview_invite(body: InviteTokenRequest, db: DB):
    return ok(await service.preview_invite(db, body.token))


_ACCEPT: dict[int | str, dict[str, Any]] = {401: _ERR, 403: _ERR, 404: _ERR, 422: _ERR}


@router.post("/accept", response_model=ApiResponse[AcceptedInvite], responses=_ACCEPT)
async def accept_invite(body: InviteTokenRequest, user: CurrentUser, db: DB):
    joined = await service.accept_invite(db, user, body.token)
    return ok(joined, message=f"Anda bergabung ke {joined.workspace_name}.")
