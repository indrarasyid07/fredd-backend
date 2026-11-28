"""Conversations of the active workspace for the dashboard (reviewer and up, roadmap 6.3)."""

import uuid
from typing import Any, Literal

from fastapi import APIRouter

from app.api.deps import DB, AdminMember, ReviewerMember
from app.api.pagination import Cursor, Limit, decode_cursor, encode_cursor
from app.api.responses import ApiErrorResponse, ApiResponse, Pagination, ok
from app.modules.conversations import inbox, jobs, takeover
from app.modules.conversations.schemas import (
    ConversationDetailOut,
    ConversationMessageOut,
    ConversationOut,
    SendConversationMessageRequest,
)

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR}
_ACTION_GUARDS: dict[int | str, dict[str, Any]] = {**_GUARDS, 409: _ERR, 422: _ERR}


@router.get("", response_model=ApiResponse[list[ConversationOut]], responses=_GUARDS)
async def list_conversations(
    member: ReviewerMember,
    db: DB,
    status: Literal["needs_help", "taken_over"] | None = None,
    limit: Limit = 20,
    cursor: Cursor = None,
):
    items, more = await inbox.list_conversations(
        db, member, status=status, after=decode_cursor(cursor, 2), limit=limit
    )
    next_cursor = encode_cursor(list(more)) if more else None
    return ok(
        items,
        pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=more is not None),
    )


@router.get(
    "/{conversation_id}", response_model=ApiResponse[ConversationDetailOut], responses=_GUARDS
)
async def get_conversation(member: ReviewerMember, db: DB, conversation_id: uuid.UUID):
    return ok(await inbox.get_conversation(db, member, conversation_id))


@router.post(
    "/{conversation_id}/takeover",
    response_model=ApiResponse[ConversationDetailOut],
    responses=_ACTION_GUARDS,
)
async def take_over_conversation(member: AdminMember, db: DB, conversation_id: uuid.UUID):
    """Answer instead of Fluctuz. 409 `conversation_taken_over` when another admin was first."""
    data = await takeover.take_over(db, member, conversation_id)
    return ok(data, message="Percakapan diambil alih. Fluctuz berhenti membalas penyuluh ini.")


@router.post(
    "/{conversation_id}/messages",
    response_model=ApiResponse[ConversationMessageOut],
    responses=_ACTION_GUARDS,
)
async def send_conversation_message(
    member: AdminMember, db: DB, conversation_id: uuid.UUID, body: SendConversationMessageRequest
):
    """Only the admin who took the conversation over; sent through the worker's channel."""
    message_id = await takeover.send_message(db, member, conversation_id, body.text)
    await jobs.deliver_message_job.kiq(str(message_id))
    detail = await inbox.get_conversation(db, member, conversation_id)
    sent = next(m for m in detail.messages if m.id == message_id)
    return ok(sent, message="Balasan dikirim.")


@router.post(
    "/{conversation_id}/release",
    response_model=ApiResponse[ConversationDetailOut],
    responses=_ACTION_GUARDS,
)
async def release_conversation(member: AdminMember, db: DB, conversation_id: uuid.UUID):
    """Hand back to Fluctuz, which carries on from the open question."""
    data, to_send = await takeover.release(db, member, conversation_id)
    for message_id in to_send:
        await jobs.deliver_message_job.kiq(str(message_id))
    return ok(data, message="Percakapan dikembalikan ke Fluctuz.")
