"""Is the shared bot healthy? (roadmap 7.4, runbook-bot.md)

Every 5 minutes the worker asks Telegram about the webhook (`getWebhookInfo`) and the database
about outgoing messages, keeps the result in Redis (`bot-health`) for `python -m
scripts.bot_health`, and logs a WARNING per problem, which is the alert: log-based alerting
picks up `bot health:` warnings. Thresholds are in this module.
"""

import datetime as dt
import json
import logging
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import redis
from app.core.time import now_utc
from app.modules.channels import telegram
from app.modules.conversations import repository

logger = logging.getLogger(__name__)

SNAPSHOT_KEY = "bot-health"
HEARTBEAT_KEY = "worker:heartbeat"  # written by app.worker every minute
# Alert when…
MAX_PENDING_UPDATES = 100  # Telegram holds this many updates it could not hand us
RECENT_ERROR = dt.timedelta(minutes=15)  # Telegram saw a webhook error this recently
MAX_OLDEST_PENDING = dt.timedelta(minutes=5)  # an outgoing message waits this long
MAX_FAILED_PER_HOUR = 50  # outgoing sends gave up in the last hour
MAX_HEARTBEAT_AGE = dt.timedelta(minutes=3)  # the worker or scheduler stopped


async def _webhook() -> dict[str, Any] | None:
    if not settings.telegram_bot_token:
        return None
    try:
        info = await telegram.get_client().call("getWebhookInfo")
    except telegram.TelegramError as exc:
        return {"error": f"{exc.status}: {exc.description}"}
    return {
        "url_set": bool(info.get("url")),
        "pending_update_count": info.get("pending_update_count", 0),
        "last_error_date": info.get("last_error_date"),
        # Telegram's own words, e.g. "Wrong response from the webhook: 502 Bad Gateway".
        "last_error_message": info.get("last_error_message"),
    }


async def _heartbeat_age(now: dt.datetime) -> float | None:
    try:
        value = await redis.get(HEARTBEAT_KEY)
    except RedisError:
        return None
    if value is None:
        return None
    text = value.decode() if isinstance(value, bytes) else value
    return (now - dt.datetime.fromisoformat(text)).total_seconds()


def problems(snapshot: dict[str, Any], now: dt.datetime) -> list[str]:
    found: list[str] = []
    webhook = snapshot.get("webhook")
    if webhook is not None:
        if "error" in webhook:
            found.append(f"getWebhookInfo failed: {webhook['error']}")
        else:
            if not webhook["url_set"]:
                found.append("telegram webhook URL is not set")
            if webhook["pending_update_count"] > MAX_PENDING_UPDATES:
                found.append(f"telegram holds {webhook['pending_update_count']} pending updates")
            error_at = webhook.get("last_error_date")
            if error_at and now - dt.datetime.fromtimestamp(error_at, dt.UTC) < RECENT_ERROR:
                found.append(f"telegram webhook error: {webhook.get('last_error_message')}")
    oldest = snapshot["outgoing"]["oldest_pending_seconds"]
    if oldest is not None and oldest > MAX_OLDEST_PENDING.total_seconds():
        found.append(f"outgoing message pending for {oldest:.0f}s")
    if snapshot["outgoing"]["failed_last_hour"] > MAX_FAILED_PER_HOUR:
        found.append(f"{snapshot['outgoing']['failed_last_hour']} sends failed in the last hour")
    age = snapshot["worker_heartbeat_seconds"]
    if age is None or age > MAX_HEARTBEAT_AGE.total_seconds():
        found.append("worker heartbeat missing or stale")
    return found


async def check(db: AsyncSession) -> dict[str, Any]:
    now = now_utc()
    stats = await repository.outgoing_stats(db, now)
    snapshot: dict[str, Any] = {
        "checked_at": now.isoformat(),
        "webhook": await _webhook(),
        "outgoing": stats,
        "worker_heartbeat_seconds": await _heartbeat_age(now),
    }
    snapshot["problems"] = problems(snapshot, now)
    return snapshot


async def check_and_alert(db: AsyncSession) -> dict[str, Any]:
    """The cron's work: check, keep the snapshot, warn per problem."""
    snapshot = await check(db)
    try:
        await redis.set(SNAPSHOT_KEY, json.dumps(snapshot), ex=900)
    except RedisError:
        logger.warning("bot health: snapshot not stored, redis unavailable")
    for problem in snapshot["problems"]:
        logger.warning("bot health: %s", problem)
    if not snapshot["problems"]:
        logger.info("bot health: ok (%s)", json.dumps(snapshot["outgoing"]))
    return snapshot
