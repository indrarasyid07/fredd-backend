"""The organization's channel log and "Susul yang gagal" (roadmap 7.2), admin only.

Only messages already owned by the workspace are listed (a stranger's messages never are:
tenant isolation). Contacts are masked and message text is left out.
"""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import InvalidCursor
from app.modules.audit import service as audit
from app.modules.channels.masking import mask_chat_id, mask_phone
from app.modules.conversations import repository
from app.modules.conversations.errors import ChannelMessageNotFound, MessageNotResendable
from app.modules.conversations.models import Message
from app.modules.conversations.schemas import ChannelLogOut, ChannelLogWorkerOut
from app.modules.workspaces.service import ActiveMember

Key = tuple[datetime, uuid.UUID]


def _key(after: list[str] | None) -> Key | None:
    if after is None:
        return None
    try:
        return datetime.fromisoformat(after[0]), uuid.UUID(after[1])
    except ValueError:
        raise InvalidCursor() from None


def failure(message: Message) -> str | None:
    if message.delivery_status == "uncertain":
        return "timeout"
    if message.delivery_status != "failed":
        return None
    error = message.error or ""
    if error.startswith("not sent: an admin"):
        return "taken_over"
    code = error.split(":", 1)[0].strip()
    if code == "403":
        return "blocked"
    if code == "None":
        return "network"
    if code.isdigit() and 400 <= int(code) < 500 and code != "429":
        return "rejected"
    return "other"


def _out(row: repository.LogRow) -> ChannelLogOut:
    message, channel, worker_name, worker_id, phone = row
    return ChannelLogOut(
        id=message.id,
        created_at=message.created_at,
        direction=message.direction,  # type: ignore[arg-type]
        channel=channel,  # type: ignore[arg-type]
        kind=message.kind,
        delivery_status=message.delivery_status,
        attempts=message.attempts,
        failure=failure(message),  # type: ignore[arg-type]
        retrying=message.retry_at is not None,
        extension_worker=(
            ChannelLogWorkerOut(id=worker_id, name=worker_name or "")
            if worker_id is not None
            else None
        ),
        contact=mask_phone(phone) if phone else mask_chat_id(message.chat_id),
        conversation_id=message.conversation_id,
    )


async def list_logs(
    db: AsyncSession,
    member: ActiveMember,
    *,
    failed_only: bool,
    after: list[str] | None,
    limit: int,
) -> tuple[list[ChannelLogOut], Key | None]:
    rows = await repository.list_channel_logs(
        db, member.workspace_id, failed_only=failed_only, after=_key(after), limit=limit
    )
    page = rows[:limit]
    more = (page[-1][0].created_at, page[-1][0].id) if len(rows) > limit else None
    return [_out(r) for r in page], more


async def resend(db: AsyncSession, member: ActiveMember, message_id: uuid.UUID) -> uuid.UUID:
    """An admin sends a failed message again ("Susul yang gagal"); the caller queues delivery.
    A bot reply held back during a takeover stays held back if the takeover still stands."""
    message = await repository.lock_workspace_message(db, member.workspace_id, message_id)
    if message is None:
        raise ChannelMessageNotFound()
    if message.direction != "out" or message.delivery_status != "failed":
        raise MessageNotResendable()
    message.delivery_status, message.retry_at, message.error = "pending", None, None
    await audit.record(
        db,
        workspace_id=member.workspace_id,
        actor_user_id=member.member.user_id,
        action="message.resent",
        target=f"message:{message_id}",
    )
    await db.commit()
    return message.id


async def get_log(db: AsyncSession, member: ActiveMember, message_id: uuid.UUID) -> ChannelLogOut:
    row = await repository.get_channel_log(db, member.workspace_id, message_id)
    if row is None:
        raise ChannelMessageNotFound()
    return _out(row)
