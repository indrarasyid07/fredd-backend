"""Fixed-window failure counters in Redis.

If Redis is down, limits are skipped and a warning is logged: an outage must
not lock every user out.
"""

import logging

from redis.exceptions import RedisError

from app.core.redis import redis

logger = logging.getLogger(__name__)


async def retry_after(key: str, limit: int) -> int | None:
    """Seconds to wait if `key` has reached `limit`, otherwise None."""
    try:
        count = await redis.get(key)
        if count is None or int(count) < limit:
            return None
        return max(await redis.ttl(key), 1)
    except RedisError:
        logger.warning("rate limit check skipped: redis unavailable", exc_info=True)
        return None


async def hit(key: str, window_seconds: int) -> None:
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            await pipe.execute()
    except RedisError:
        logger.warning("rate limit hit not recorded: redis unavailable", exc_info=True)


async def reset(*keys: str) -> None:
    try:
        await redis.delete(*keys)
    except RedisError:
        logger.warning("rate limit reset skipped: redis unavailable", exc_info=True)
