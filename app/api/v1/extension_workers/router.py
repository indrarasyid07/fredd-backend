"""Extension workers of the active workspace: list (reviewer), and approve or block a request
to join (admin, roadmap 4.6). Approval is served by conversations, which tells the worker."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import DB, AdminMember, ReviewerMember
from app.api.pagination import Cursor, Limit, decode_cursor, encode_cursor
from app.api.responses import ApiErrorResponse, ApiResponse, Pagination, ok
from app.modules.conversations import jobs as chat_jobs
from app.modules.conversations import service as conversations
from app.modules.extension_workers import service
from app.modules.extension_workers.schemas import ExtensionWorkerOut, ExtensionWorkerStatus

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR}


@router.get("", response_model=ApiResponse[list[ExtensionWorkerOut]], responses=_GUARDS)
async def list_extension_workers(
    member: ReviewerMember,
    db: DB,
    status: Annotated[ExtensionWorkerStatus | None, Query(description="Saring status.")] = None,
    limit: Limit = 20,
    cursor: Cursor = None,
):
    items, more = await service.list_workers(
        db, member.workspace_id, status=status, after=decode_cursor(cursor, 2), limit=limit
    )
    next_cursor = encode_cursor(list(more)) if more else None
    return ok(
        items,
        pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=more is not None),
    )


@router.post(
    "/{worker_id}/approve",
    response_model=ApiResponse[ExtensionWorkerOut],
    responses={**_GUARDS, 409: _ERR},
)
async def approve_extension_worker(worker_id: uuid.UUID, member: AdminMember, db: DB):
    worker, to_send = await conversations.approve_worker(
        db, member.workspace_id, worker_id, member.member.user_id
    )
    for message_id in to_send:
        await chat_jobs.deliver_message_job.kiq(str(message_id))
    return ok(worker, message="Penyuluh disetujui dan sudah diberi tahu lewat chat.")


@router.post(
    "/{worker_id}/block",
    response_model=ApiResponse[ExtensionWorkerOut],
    responses={**_GUARDS, 409: _ERR},
)
async def block_extension_worker(worker_id: uuid.UUID, member: AdminMember, db: DB):
    worker = await service.block(db, member.workspace_id, worker_id, member.member.user_id)
    return ok(await service.describe(db, worker), message="Permintaan bergabung ditolak.")
