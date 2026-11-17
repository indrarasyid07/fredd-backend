from redis.asyncio import Redis

from app.core.config import settings

redis = Redis.from_url(
    settings.redis_url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True
)
