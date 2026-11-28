"""Conversations as the dashboard reads them (roadmap 6.3): the "Perlu bantuan admin" queue and
one conversation's latest messages. Reviewer and up; always scoped to the member's workspace."""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import InvalidCursor
from app.modules.activity import service as activity
from app.modules.activity.models import ActivityEvent
from app.modules.activity.schemas import ActivityWorkerOut
from app.modules.conversations import repository
from app.modules.conversations.errors import ConversationNotFound
from app.modules.conversations.schemas import (
    ConversationDetailOut,
    ConversationFormOut,
    ConversationHelpOut,
    ConversationMessageOut,
    ConversationOut,
)
from app.modules.workspaces.service import ActiveMember

Key = tuple[datetime, uuid.UUID]
MESSAGES_SHOWN = 50


def _key(after: list[str] | None) -> Key | None:
    if after is None:
        return None
    try:
        return datetime.fromisoformat(after[0]), uuid.UUID(after[1])
    except ValueError:
        raise InvalidCursor() from None


def _help(event: ActivityEvent | None) -> ConversationHelpOut | None:
    if event is None:
        return None
    return ConversationHelpOut(
        reason=event.details.get("reason", "asked_for_help"),
        field=event.details.get("field"),
        field_label=event.details.get("field_label"),
        at=event.occurred_at,
    )


def _out(row: repository.ConversationRow, help: ActivityEvent | None) -> ConversationOut:
    conversation, worker_name, form_name, channel = row
    return ConversationOut(
        id=conversation.id,
        status=conversation.status,
        channel=channel,  # type: ignore[arg-type]
        extension_worker=ActivityWorkerOut(id=conversation.extension_worker_id, name=worker_name),
        form=ConversationFormOut(id=conversation.form_id, name=form_name),
        step=conversation.step,
        last_inbound_at=conversation.last_inbound_at,
        updated_at=conversation.updated_at,
        help=_help(help) if conversation.status == "needs_help" else None,
    )


async def list_conversations(
    db: AsyncSession,
    member: ActiveMember,
    *,
    status: str | None,
    after: list[str] | None,
    limit: int,
) -> tuple[list[ConversationOut], Key | None]:
    rows = await repository.list_conversations(
        db, member.workspace_id, status=status, after=_key(after), limit=limit
    )
    page = rows[:limit]
    more = (page[-1][0].updated_at, page[-1][0].id) if len(rows) > limit else None
    helps = await activity.latest_help(
        db, member.workspace_id, [r[0].id for r in page if r[0].status == "needs_help"]
    )
    return [_out(r, helps.get(r[0].id)) for r in page], more


async def get_conversation(
    db: AsyncSession, member: ActiveMember, conversation_id: uuid.UUID
) -> ConversationDetailOut:
    row = await repository.get_conversation_row(db, member.workspace_id, conversation_id)
    if row is None:
        raise ConversationNotFound()
    helps = await activity.latest_help(db, member.workspace_id, [conversation_id])
    messages = await repository.latest_messages(
        db, member.workspace_id, conversation_id, MESSAGES_SHOWN
    )
    return ConversationDetailOut(
        **_out(row, helps.get(conversation_id)).model_dump(),
        messages=[
            ConversationMessageOut(
                id=m.id,
                direction=m.direction,  # type: ignore[arg-type]
                kind=m.kind,
                body=m.body,
                delivery_status=m.delivery_status,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )
