"""Chat jobs (Taskiq, B-XXX). Thin: lock, open a session, call the service."""

import asyncio
import logging
import secrets
import uuid

from app.core.queue import broker
from app.core.redis import redis
from app.db import session as db_session
from app.modules.channels import telegram
from app.modules.conversations import reminders, service, takeover

logger = logging.getLogger(__name__)

LOCK_SECONDS = 120
# Longest a chat waits for an album that keeps growing (Telegram allows 10 photos).
ALBUM_MAX_WAIT_SECONDS = 6.0


def _lock_key(channel_id: str, chat_id: str) -> str:
    return f"chat-lock:{channel_id}:{chat_id}"


@broker.task(task_name="conversations.process", retry_on_error=True)
async def process_chat_job(channel_id: str, chat_id: str) -> None:
    """One processor per chat at a time (3.5c). A job that finds the chat locked returns: the
    holder checks for new messages again after releasing the lock, so nothing is left behind."""
    key = _lock_key(channel_id, chat_id)
    while True:
        token = secrets.token_hex(8)
        if not await redis.set(key, token, nx=True, ex=LOCK_SECONDS):
            return
        try:
            await _wait_for_album(uuid.UUID(channel_id), chat_id)
            async with db_session.open_session() as db:
                to_send = await service.process_chat(
                    db, telegram.get_client(), uuid.UUID(channel_id), chat_id
                )
                for message_id in to_send:
                    await service.deliver(db, telegram.get_client(), message_id)
        finally:
            if await redis.get(key) == token:
                await redis.delete(key)
        async with db_session.open_session() as db:
            if not await service.has_unprocessed(db, uuid.UUID(channel_id), chat_id):
                return


async def _wait_for_album(channel_id: uuid.UUID, chat_id: str) -> None:
    """Under the chat lock: the album's later photos are stored by their own webhooks meanwhile,
    and their jobs return at the lock, so one run answers the whole album (3.5b)."""
    waited = 0.0
    while waited < ALBUM_MAX_WAIT_SECONDS:
        async with db_session.open_session() as db:
            pause = await service.album_wait(db, channel_id, chat_id)
        if pause <= 0:
            return
        pause = min(pause, ALBUM_MAX_WAIT_SECONDS - waited)
        await asyncio.sleep(pause)
        waited += pause


@broker.task(task_name="conversations.deliver", retry_on_error=True)
async def deliver_message_job(message_id: str) -> None:
    """Send one outbound row made outside a chat's own processing (e.g. an admin's approval)."""
    async with db_session.open_session() as db:
        await service.deliver(db, telegram.get_client(), uuid.UUID(message_id))


@broker.task(task_name="conversations.leave_chat")
async def leave_chat_job(chat_id: str) -> None:
    """The bot only works in private chats; it leaves any group it is added to (3.5a)."""
    try:
        await telegram.get_client().leave_chat(chat_id)
    except telegram.TelegramError as exc:
        logger.info("leaveChat failed: %s", exc.status)


@broker.task(task_name="conversations.release_stale_takeovers", schedule=[{"cron": "*/10 * * * *"}])
async def release_stale_takeovers_job() -> None:
    """Every 10 minutes: takeovers idle for 4 hours come back to Fluctuz (roadmap 6.4)."""
    async with db_session.open_session() as db:
        to_send = await takeover.release_stale(db)
    for message_id in to_send:
        await deliver_message_job.kiq(str(message_id))


@broker.task(task_name="conversations.send_draft_reminders", schedule=[{"cron": "*/5 * * * *"}])
async def send_draft_reminders_job() -> None:
    """Every 5 minutes: draft reminders that are due, outside quiet hours (roadmap 7.1)."""
    async with db_session.open_session() as db:
        to_send = await reminders.send_due(db)
    for message_id in to_send:
        await deliver_message_job.kiq(str(message_id))
