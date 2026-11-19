"""Inbound chat pipeline: store each update once, then process a chat's messages in order.

Webhook (request): `receive_telegram` stores the update and says which chat to process.
Worker (job): `process_chat` runs the chat's unprocessed messages oldest first and records the
replies as `pending` outbound rows in the same transaction; `deliver` sends each one and records
`sent`, `uncertain` (timeout: maybe delivered, never resent automatically) or `failed`.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.channels import service as channels
from app.modules.channels.telegram import (
    BotBlocked,
    InboundUpdate,
    LeaveGroup,
    TelegramClient,
    TelegramError,
    parse_update,
)
from app.modules.conversations import repository
from app.modules.conversations.engine import copy
from app.modules.conversations.engine.types import Button, Outbound
from app.modules.conversations.models import Message

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Received:
    """What the webhook should queue next."""

    process: tuple[uuid.UUID, str] | None = None  # (channel_id, chat_id) with a new message
    leave_chat: str | None = None


async def receive_telegram(db: AsyncSession, update: dict[str, object]) -> Received:
    parsed = parse_update(update)
    if parsed is None:
        return Received()
    if isinstance(parsed, LeaveGroup):
        return Received(leave_chat=parsed.chat_id)
    if isinstance(parsed, BotBlocked):
        # In a private chat the chat id is the user id.
        count = await repository.mark_unreachable(db, parsed.chat_id, now_utc())
        await db.commit()
        if count:
            logger.info("telegram user blocked the bot; %d extension workers unreachable", count)
        return Received()
    return await _store(db, parsed)


async def _store(db: AsyncSession, upd: InboundUpdate) -> Received:
    channel = await channels.telegram_channel(db)
    is_new = await repository.insert_inbound(
        db,
        {
            "channel_id": channel.id,
            "chat_id": upd.chat_id,
            "kind": upd.kind,
            "body": upd.body,
            "payload": {"update_id": upd.update_id, **upd.payload},
            "external_id": upd.external_id,
            "channel_sent_at": upd.sent_at,
        },
    )
    await db.commit()
    return Received(process=(channel.id, upd.chat_id)) if is_new else Received()


# --- Processing (worker) ------------------------------------------------------------------------


def _replies_for_unbound(message: Message) -> list[Outbound]:
    """A chat with no organization yet. Nothing is created in any workspace (tenant isolation);
    the only answer is how to join. Claiming a code comes with roadmap 3.6."""
    if message.payload.get("edited"):
        return [Outbound(copy.EDITED)]
    return [Outbound(copy.JOIN_FIRST)]


async def process_chat(
    db: AsyncSession, client: TelegramClient, channel_id: uuid.UUID, chat_id: str
) -> list[uuid.UUID]:
    """Process every unprocessed inbound message of one chat; returns the outbound rows to send.

    The caller holds the chat lock, so messages are handled one at a time in send order.
    """
    messages = await repository.list_unprocessed(db, channel_id, chat_id)
    if not messages:
        return []
    context = await repository.get_chat_context(db, channel_id, chat_id)
    replies: list[Outbound] = []
    for message in messages:
        if message.kind == "button" and (callback_id := message.payload.get("callback_id")):
            try:
                await client.answer_callback(str(callback_id))
            except TelegramError as exc:  # expired callbacks are harmless
                logger.info("answerCallbackQuery failed: %s", exc.status)
        if context is None:
            for reply in _replies_for_unbound(message):
                # A burst of messages from a stranger gets one answer, not one per message.
                if not replies or replies[-1] != reply:
                    replies.append(reply)
        # Bound chats (topic, engine state, reports) are processed from roadmap 3.6/3.7.
        message.processed_at = now_utc()

    outbound = [
        Message(
            channel_id=channel_id,
            chat_id=chat_id,
            direction="out",
            kind="text",
            body=reply.text,
            payload=_payload(reply),
            delivery_status="pending",
        )  # fmt: skip
        for reply in replies
    ]
    db.add_all(outbound)
    await db.commit()
    return [m.id for m in outbound]


def _payload(reply: Outbound) -> dict[str, object]:
    return {
        "buttons": [{"label": b.label, "value": b.value} for b in reply.buttons],
        "ask_location": reply.ask_location,
    }


def _outbound(message: Message) -> Outbound:
    buttons = tuple(Button(b["label"], b["value"]) for b in message.payload.get("buttons", []))
    return Outbound(
        message.body or "", buttons=buttons, ask_location=bool(message.payload.get("ask_location"))
    )


async def deliver(db: AsyncSession, client: TelegramClient, message_id: uuid.UUID) -> None:
    """Send one pending outbound row. Never resends a row that is not `pending` (no doubles)."""
    message = await db.scalar(
        select(Message).where(Message.id == message_id).with_for_update(skip_locked=True)
    )
    if message is None or message.delivery_status != "pending":
        return
    message.attempts += 1
    try:
        external_id = await client.send(message.chat_id, _outbound(message))
    except TelegramError as exc:
        message.delivery_status = "uncertain" if exc.timed_out else "failed"
        message.error = f"{exc.status}: {exc.description}"[:300]
        if exc.status == 403:  # blocked by the user
            await repository.mark_unreachable(db, message.chat_id, now_utc())
    else:
        message.delivery_status = "sent"
        # Telegram message ids are unique per chat, not per bot.
        message.external_id = f"message:{message.chat_id}:{external_id}"
    await db.commit()


async def has_unprocessed(db: AsyncSession, channel_id: uuid.UUID, chat_id: str) -> bool:
    return await repository.has_unprocessed(db, channel_id, chat_id)
