"""Conversations of the active workspace for the dashboard (reviewer and up, roadmap 6.3)."""

import uuid
from typing import Any, Literal

from fastapi import APIRouter

from app.api.deps import DB, ReviewerMember
from app.api.pagination import Cursor, Limit, decode_cursor, encode_cursor
from app.api.responses import ApiErrorResponse, ApiResponse, Pagination, ok
from app.modules.conversations import inbox
from app.modules.conversations.schemas import ConversationDetailOut, ConversationOut

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR}


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
