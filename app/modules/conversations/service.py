"""Inbound chat pipeline: store each update once, then process a chat's messages in order.

Webhook (request): `receive_telegram` stores the update and says which chat to process.
Worker (job): `process_chat` runs the chat's unprocessed messages oldest first and records the
replies as `pending` outbound rows in the same transaction; `deliver` sends each one and records
`sent`, `uncertain` (timeout: maybe delivered, never resent automatically) or `failed`.
"""

import logging
import uuid
from dataclasses import dataclass, field

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import redis
from app.core.time import now_utc
from app.modules.agent import service as agent_settings
from app.modules.ai import speech
from app.modules.channels import service as channels
from app.modules.channels.telegram import (
    BotApi,
    BotBlocked,
    InboundUpdate,
    LeaveGroup,
    TelegramError,
    parse_update,
)
from app.modules.conversations import joining, media, reporting, repository
from app.modules.conversations.engine import copy
from app.modules.conversations.engine.types import Button, ConversationState, Outbound
from app.modules.conversations.models import Message
from app.modules.extension_workers import service as workers
from app.modules.extension_workers.schemas import ExtensionWorkerOut
from app.modules.forms import service as forms
from app.modules.reports import jobs as report_jobs
from app.modules.reports import photo_checks
from app.modules.workspaces import service as workspaces

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Received:
    """What the webhook should queue next."""

    process: tuple[uuid.UUID, str] | None = None  # (channel_id, chat_id) with a new message
    leave_chat: str | None = None
    # Outbound rows made at receive time (the rate-limit notice), to deliver.
    deliver: list[uuid.UUID] = field(default_factory=list)


# Anti-spam per chat identity (roadmap 3.6): room for a 10-photo album and quick answers.
MAX_MESSAGES_PER_MINUTE = 30
RATE_WINDOW_SECONDS = 60


async def _count_message(channel_id: uuid.UUID, chat_id: str) -> int:
    """This chat's messages in the current minute, this one included; 0 when Redis is down
    (an outage must not silence every chat)."""
    key = f"chat-rate:{channel_id}:{chat_id}"
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, RATE_WINDOW_SECONDS, nx=True)
            count, _ = await pipe.execute()
        return int(count)
    except RedisError:
        logger.warning("chat rate limit skipped: redis unavailable", exc_info=True)
        return 0


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
    count = await _count_message(channel.id, upd.chat_id)
    if count > MAX_MESSAGES_PER_MINUTE:
        # Not stored, not processed. The first message over the limit gets one notice.
        if count == MAX_MESSAGES_PER_MINUTE + 1:
            logger.info("telegram chat over %d messages/minute", MAX_MESSAGES_PER_MINUTE)
            return Received(deliver=[await _notice(db, channel.id, upd.chat_id)])
        return Received()
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


async def _notice(db: AsyncSession, channel_id: uuid.UUID, chat_id: str) -> uuid.UUID:
    reply = Outbound(copy.RATE_LIMITED)
    workspace_id, conversation_id = await _owner(db, joining.Chat(channel_id, chat_id))
    message = Message(
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        channel_id=channel_id,
        chat_id=chat_id,
        direction="out",
        kind="text",
        body=reply.text,
        payload=_payload(reply),
        delivery_status="pending",
    )
    db.add(message)
    await db.commit()
    return message.id


# --- Processing (worker) ------------------------------------------------------------------------


async def process_chat(
    db: AsyncSession, client: BotApi, channel_id: uuid.UUID, chat_id: str
) -> list[uuid.UUID]:
    """Process every unprocessed inbound message of one chat; returns the outbound rows to send.

    The caller holds the chat lock, so messages are handled one at a time in send order.
    """
    messages = await repository.list_unprocessed(db, channel_id, chat_id)
    if not messages:
        return []
    chat = joining.Chat(channel_id, chat_id)
    replies: list[tuple[Outbound, Owner]] = []
    for message in messages:
        if message.kind == "button" and (callback_id := message.payload.get("callback_id")):
            try:
                await client.answer_callback(str(callback_id))
            except TelegramError as exc:  # expired callbacks are harmless
                logger.info("answerCallbackQuery failed: %s", exc.status)
        answer = await joining.route(db, chat, message)
        if answer is None:
            # A chat with a topic, not about joining: the report flow (roadmap 3.7).
            if message.payload.get("edited"):
                answer = [Outbound(copy.EDITED)]
            else:
                await _store_media(db, client, chat, message)
                answer = await reporting.handle(db, chat, message)
        db.info.pop(joining.BACK_TO_TOPIC, None)  # never carried over to the next message
        # After routing, so the message that joined a topic belongs to it too.
        owner = await _owner(db, chat)
        message.workspace_id, message.conversation_id = owner
        await workers.touch(db, channel_id, chat_id, message.channel_sent_at or now_utc())
        for reply in answer:
            # A burst of messages from a stranger gets one answer, not one per message.
            if not replies or replies[-1][0] != reply:
                replies.append((reply, owner))
        message.processed_at = now_utc()

    outbound = [
        Message(
            workspace_id=owner[0],
            conversation_id=owner[1],
            channel_id=channel_id,
            chat_id=chat_id,
            direction="out",
            kind="text",
            body=reply.text,
            payload=_payload(reply),
            delivery_status="pending",
        )  # fmt: skip
        for reply, owner in replies
    ]
    db.add_all(outbound)
    await db.commit()
    await _after_reports(db, db.info.pop(reporting.NEW_REPORTS, []))
    return [m.id for m in outbound]


async def _after_reports(db: AsyncSession, created: list[tuple[uuid.UUID, uuid.UUID]]) -> None:
    """Background work on reports this chat just submitted: AI photo notes (roadmap 12.7), when
    the organization lets its agent read photos (Pengaturan agent)."""
    if not created or not photo_checks.enabled():
        return
    for workspace_id, report_id in created:
        if not (await agent_settings.get_settings(db, workspace_id)).voice_and_photos:
            continue
        try:
            await report_jobs.check_photos_job.kiq(str(workspace_id), str(report_id))
        except Exception:  # the queue being down must not fail a chat that already committed
            logger.warning("photo check not queued for report %s", report_id, exc_info=True)


Owner = tuple[uuid.UUID | None, uuid.UUID | None]


async def _store_media(
    db: AsyncSession, client: BotApi, chat: joining.Chat, message: Message
) -> None:
    """Copy a photo or file to storage under the organization of the chat's active topic, the
    one the report flow answers for (roadmap 3.8)."""
    if message.kind not in media.MEDIA_KINDS:
        return
    assignment = await workers.active_assignment(db, chat.channel_id, chat.chat_id)
    if assignment is None:
        return
    data = await media.store(client, message, assignment.workspace_id)
    if message.kind == "voice" and data is not None:
        form = await forms.get_form(db, assignment.workspace_id, assignment.form_id)
        if (form.settings or {}).get("input_mode") == "voice":
            await _transcribe(message, data)
        elif speech.transcribes_every_voice_note():
            # Any other topic: the voice note answers the open question like typed text, when
            # the organization lets its agent take voice notes (Pengaturan agent).
            agent = await agent_settings.get_settings(db, assignment.workspace_id)
            if agent.voice_and_photos:
                await _transcribe(message, data, as_answer=True)


async def _transcribe(message: Message, audio: bytes, *, as_answer: bool = False) -> None:
    """A voice note as text: a voice-mode topic's report sentence (Voice Lab, roadmap 12.3), or
    (`as_answer`) a spoken answer in any other topic (roadmap 12.7). A failing provider leaves
    the note untranscribed; the bot then asks to resend or type it."""
    content_type = str(message.payload.get("content_type") or "audio/ogg")
    try:
        transcript = await speech.get_speech_to_text().transcribe(audio, content_type)
    except Exception:  # any provider failure: never lose the message over it
        logger.warning("voice note not transcribed", exc_info=True)
        return
    message.payload = {
        **message.payload,
        "transcript": transcript.text,
        "stt_provider": transcript.provider,
        **({"transcribed_as": "answer"} if as_answer else {}),
    }


async def _owner(db: AsyncSession, chat: joining.Chat) -> Owner:
    """The organization and conversation of the chat's active topic; (None, None) for a chat
    without one, so a stranger's messages never belong to any organization."""
    assignment = await workers.active_assignment(db, chat.channel_id, chat.chat_id)
    if assignment is None:
        return None, None
    conversation = await repository.get_conversation(
        db, assignment.extension_worker_id, assignment.form_id
    )
    return assignment.workspace_id, conversation.id if conversation is not None else None


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


async def deliver(db: AsyncSession, client: BotApi, message_id: uuid.UUID) -> None:
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


async def chat_history(
    db: AsyncSession, channel_id: uuid.UUID, chat_id: str, limit: int = 200
) -> list[Message]:
    return await repository.list_chat_messages(db, channel_id, chat_id, limit)


# --- Admin approval (roadmap 4.6) ---------------------------------------------------------------


async def approve_worker(
    db: AsyncSession, workspace_id: uuid.UUID, worker_id: uuid.UUID, actor_user_id: uuid.UUID
) -> tuple[ExtensionWorkerOut, list[uuid.UUID]]:
    """Approve a waiting worker and tell them in their chat. Their topic opens with the usual
    "Ya, tetap / Bukan, ganti" question, unless the chat moved on to another topic meanwhile.
    Returns the outbound rows the caller queues for delivery."""
    worker, assignment = await workers.approve(db, workspace_id, worker_id, actor_user_id)
    conversation = (
        await repository.get_conversation(db, worker.id, assignment.form_id)
        if assignment is not None
        else None
    )
    outbound: list[Message] = []
    if assignment is not None and conversation is not None:
        organization = await workspaces.get_name(db, workspace_id)
        topic = (await forms.get_form(db, workspace_id, assignment.form_id)).name
        channel_id, chat_id = conversation.channel_id, conversation.chat_id
        busy = await workers.active_assignment(db, channel_id, chat_id)
        if busy is None:
            await workers.set_active(db, channel_id, chat_id, assignment.id)
            conversation.status = "joining"
            conversation.state = ConversationState(
                status="joining", topic_id=str(assignment.form_id)
            ).to_json()
            first = worker.name.split()[0] if worker.name else None
            reply = Outbound(
                copy.approved(first, organization, topic, settings.privacy_policy_url),
                buttons=(Button(copy.KEEP, joining.KEEP), Button(copy.NOT_MINE, joining.CHANGE)),
            )
            owner: Owner = (workspace_id, conversation.id)
        else:
            reply = Outbound(copy.approved_elsewhere(organization, topic))
            owner = await _owner(db, joining.Chat(channel_id, chat_id))
        outbound.append(
            Message(
                workspace_id=owner[0],
                conversation_id=owner[1],
                channel_id=channel_id,
                chat_id=chat_id,
                direction="out",
                kind="text",
                body=reply.text,
                payload=_payload(reply),
                delivery_status="pending",
            )
        )
        db.add_all(outbound)
    await db.commit()
    return await workers.describe(db, worker), [m.id for m in outbound]
