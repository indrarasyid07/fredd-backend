"""Extension workers of the active workspace (roadmap 4.4 and 4.6): list, summary and detail
(reviewer); edit, approve, block and unblock (admin). Approval is served by conversations, which
tells the worker in their chat."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import DB, AdminMember, ReviewerMember
from app.api.pagination import Cursor, Limit, decode_cursor, encode_cursor
from app.api.responses import ApiErrorResponse, ApiResponse, Pagination, ok
from app.modules.conversations import identity_move
from app.modules.conversations import jobs as chat_jobs
from app.modules.conversations import service as conversations
from app.modules.extension_workers import service
from app.modules.extension_workers.schemas import (
    ExtensionWorkerDetailOut,
    ExtensionWorkerOut,
    ExtensionWorkerStatus,
    ExtensionWorkerSummaryOut,
    MoveIdentityRequest,
    UpdateExtensionWorkerRequest,
    WorkerSort,
)

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR}
_ACTION = {**_GUARDS, 409: _ERR}


@router.get("", response_model=ApiResponse[list[ExtensionWorkerOut]], responses=_GUARDS)
async def list_extension_workers(
    member: ReviewerMember,
    db: DB,
    status: Annotated[
        list[ExtensionWorkerStatus] | None,
        Query(description="Saring status (boleh lebih dari satu)."),
    ] = None,
    channel: Annotated[str | None, Query(pattern="^(telegram|whatsapp)$")] = None,
    form_id: Annotated[uuid.UUID | None, Query(description="Punya topik aktif ini.")] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100, description="Cari nama.")] = None,
    sort: WorkerSort = "newest",
    limit: Limit = 20,
    cursor: Cursor = None,
):
    items, more = await service.list_workers(
        db,
        member.workspace_id,
        statuses=list(status) if status else None,
        channel=channel,
        form_id=form_id,
        query=q,
        sort=sort,
        after=decode_cursor(cursor, 2),
        limit=limit,
    )
    next_cursor = encode_cursor(more) if more else None
    return ok(
        items,
        pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=more is not None),
    )


@router.get("/summary", response_model=ApiResponse[ExtensionWorkerSummaryOut], responses=_GUARDS)
async def extension_worker_summary(member: ReviewerMember, db: DB):
    return ok(await service.summary(db, member.workspace_id))


@router.get("/{worker_id}", response_model=ApiResponse[ExtensionWorkerDetailOut], responses=_GUARDS)
async def get_extension_worker(worker_id: uuid.UUID, member: ReviewerMember, db: DB):
    return ok(await service.get_detail(db, member.workspace_id, worker_id))


@router.patch(
    "/{worker_id}",
    response_model=ApiResponse[ExtensionWorkerDetailOut],
    responses={**_GUARDS, 422: _ERR},
)
async def update_extension_worker(
    worker_id: uuid.UUID, body: UpdateExtensionWorkerRequest, member: AdminMember, db: DB
):
    worker = await service.update(db, member.workspace_id, worker_id, body, member.member.user_id)
    return ok(worker, message="Data penyuluh disimpan.")


@router.post(
    "/{worker_id}/approve", response_model=ApiResponse[ExtensionWorkerOut], responses=_ACTION
)
async def approve_extension_worker(worker_id: uuid.UUID, member: AdminMember, db: DB):
    worker, to_send = await conversations.approve_worker(
        db, member.workspace_id, worker_id, member.member.user_id
    )
    for message_id in to_send:
        await chat_jobs.deliver_message_job.kiq(str(message_id))
    return ok(worker, message="Penyuluh disetujui dan sudah diberi tahu lewat chat.")


@router.post(
    "/{worker_id}/block", response_model=ApiResponse[ExtensionWorkerOut], responses=_ACTION
)
async def block_extension_worker(worker_id: uuid.UUID, member: AdminMember, db: DB):
    worker, was_pending = await service.block(
        db, member.workspace_id, worker_id, member.member.user_id
    )
    message = "Permintaan bergabung ditolak." if was_pending else "Penyuluh diblokir."
    return ok(await service.describe(db, worker), message=message)


@router.post(
    "/{worker_id}/unblock", response_model=ApiResponse[ExtensionWorkerOut], responses=_ACTION
)
async def unblock_extension_worker(worker_id: uuid.UUID, member: AdminMember, db: DB):
    worker = await service.unblock(db, member.workspace_id, worker_id, member.member.user_id)
    return ok(
        await service.describe(db, worker),
        message="Blokir dibuka. Penyuluh bisa bergabung lagi dengan mengirim kode.",
    )


@router.post(
    "/{worker_id}/move-identity",
    response_model=ApiResponse[ExtensionWorkerDetailOut],
    responses={**_ACTION, 422: _ERR},
)
async def move_extension_worker_identity(
    worker_id: uuid.UUID, body: MoveIdentityRequest, member: AdminMember, db: DB
):
    """The worker changed phone or Telegram account (roadmap 7.5): this record takes the new
    identity from the record their new account made; topics, drafts and reports come along."""
    await identity_move.move_identity(db, member, worker_id, body.from_extension_worker_id)
    detail = await service.get_detail(db, member.workspace_id, worker_id)
    return ok(detail, message="Penyuluh dipindahkan ke akun barunya. Riwayatnya tetap utuh.")
