"""The organization's channel log on the shared bots (admin, roadmap 7.2)."""

import uuid
from typing import Any, Literal

from fastapi import APIRouter

from app.api.deps import DB, AdminMember
from app.api.pagination import Cursor, Limit, decode_cursor, encode_cursor
from app.api.responses import ApiErrorResponse, ApiResponse, Pagination, ok
from app.modules.conversations import channel_logs, jobs
from app.modules.conversations.schemas import ChannelLogOut

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR}


@router.get("/logs", response_model=ApiResponse[list[ChannelLogOut]], responses=_GUARDS)
async def list_channel_logs(
    member: AdminMember,
    db: DB,
    status: Literal["failed"] | None = None,
    limit: Limit = 20,
    cursor: Cursor = None,
):
    """Messages in and out, newest first, contacts masked, no message text. `status=failed`:
    sends Fluctuz gave up on ("Susul yang gagal")."""
    items, more = await channel_logs.list_logs(
        db, member, failed_only=status == "failed", after=decode_cursor(cursor, 2), limit=limit
    )
    next_cursor = encode_cursor(list(more)) if more else None
    return ok(
        items,
        pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=more is not None),
    )


@router.post(
    "/logs/{message_id}/resend",
    response_model=ApiResponse[ChannelLogOut],
    responses={**_GUARDS, 409: _ERR},
)
async def resend_message(member: AdminMember, db: DB, message_id: uuid.UUID):
    """Send a failed message again; 409 `message_not_resendable` for anything else."""
    await channel_logs.resend(db, member, message_id)
    await jobs.deliver_message_job.kiq(str(message_id))
    return ok(await channel_logs.get_log(db, member, message_id), message="Pesan dikirim ulang.")
