"""Fair sending on the shared bots (roadmap 7.3, conversation-engine.md "Antrean kirim yang adil").

One bot serves every organization, so the channel's limits are shared:

- **Per bot:** at most `BOT_PER_SECOND` sends a second (Telegram allows about 30). Proactive
  messages (reminders, later announcements) may use only `PROACTIVE_PER_SECOND` of them, so
  replies in a live conversation always find room.
- **Per chat:** at most one send a second to the same chat (Telegram's per-chat limit).
- **Per organization:** proactive messages draw on a budget of
  `PROACTIVE_PER_MINUTE` a minute (`send-budget:{workspace_id}:{minute}`), so one organization's
  reminders cannot crowd out the others'. One default for now; per plan with billing (9.1).

Fixed one-second / one-minute windows in Redis, shared by every worker. If Redis is down the
limits are skipped (a warning is logged): a Redis outage must not stop the bot answering.
"""

import asyncio
import logging
import time
import uuid

from redis.exceptions import RedisError

from app.core.redis import redis

logger = logging.getLogger(__name__)

BOT_PER_SECOND = 30
PROACTIVE_PER_SECOND = 20
CHAT_PER_SECOND = 1
PROACTIVE_PER_MINUTE = 30
# A send waits at most this long for a slot, then goes anyway (Telegram's 429 is retried, 7.2).
MAX_WAIT_SECONDS = 10.0


def _now() -> float:
    return time.time()


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def _take(key: str, limit: int, ttl: int, *, only_below: bool = False) -> bool:
    """Count one send in `key`'s window; False when the window is full. `only_below` looks
    first, so a refused proactive send does not use up room meant for replies."""
    if only_below:
        current = await redis.get(key)
        if current is not None and int(current) >= limit:
            return False
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, ttl, nx=True)
        count, _ = await pipe.execute()
    return int(count) <= limit


async def wait_for_slot(channel: str, chat_id: str, *, proactive: bool) -> float:
    """Wait until this send fits the bot's and the chat's limits; returns the seconds waited."""
    waited = 0.0
    while True:
        second = int(_now())
        try:
            bot_limit = PROACTIVE_PER_SECOND if proactive else BOT_PER_SECOND
            if await _take(
                f"send-rate:{channel}:{second}", bot_limit, 2, only_below=proactive
            ) and await _take(f"send-chat:{channel}:{chat_id}:{second}", CHAT_PER_SECOND, 2):
                return waited
        except RedisError:
            logger.warning("send limits skipped: redis unavailable", exc_info=True)
            return waited
        if waited >= MAX_WAIT_SECONDS:
            logger.warning("send slot not found in %.0fs on %s; sending anyway", waited, channel)
            return waited
        pause = max(second + 1 - _now(), 0.05)
        await _sleep(pause)
        waited += pause


async def take_budget(workspace_id: uuid.UUID) -> bool:
    """One proactive message from this organization's budget for the current minute."""
    minute = int(_now() // 60)
    try:
        return await _take(f"send-budget:{workspace_id}:{minute}", PROACTIVE_PER_MINUTE, 120)
    except RedisError:
        logger.warning("send budget skipped: redis unavailable", exc_info=True)
        return True
