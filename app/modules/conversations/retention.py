"""Retention (roadmap 7.4): chat messages and report photos do not stay forever.

Defaults: messages 12 months, photos 24 months, both per workspace in
`workspaces.settings["retention"]` (`messages_months`, `photos_months`). A daily cron deletes in
batches, so a large backlog is worked off over a few nights instead of one long lock. A chat
photo that is also a report photo keeps its file until the photo's own retention ends.
"""

import datetime as dt
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_storage
from app.core.time import now_utc
from app.modules.conversations import repository
from app.modules.reports import service as reports

logger = logging.getLogger(__name__)

MESSAGES_MONTHS = 12
PHOTOS_MONTHS = 24
BATCH = 1000


def months(settings: dict[str, Any] | None, key: str, default: int) -> int:
    value = ((settings or {}).get("retention") or {}).get(key)
    return value if isinstance(value, int) and value >= 1 else default


def _before(n_months: int, now: dt.datetime) -> dt.datetime:
    return now - dt.timedelta(days=30 * n_months)


async def _delete_messages(
    db: AsyncSession, workspace_id: uuid.UUID | None, before: dt.datetime
) -> int:
    rows = await repository.list_expired_messages(db, workspace_id, before, BATCH)
    if not rows:
        return 0
    keys = [key for _, key in rows if key]
    kept = await reports.photo_keys_in_use(db, keys)
    storage = get_storage()
    for key in keys:
        if key not in kept:
            await storage.delete(key)
    await repository.delete_messages(db, [message_id for message_id, _ in rows])
    return len(rows)


async def apply(db: AsyncSession) -> dict[str, int]:
    """One night's work for every workspace; returns what was deleted."""
    now = now_utc()
    deleted = {"messages": 0, "photos": 0}
    workspaces = await repository.list_workspace_settings(db)
    for workspace_id, settings in workspaces:
        message_cutoff = _before(months(settings, "messages_months", MESSAGES_MONTHS), now)
        deleted["messages"] += await _delete_messages(db, workspace_id, message_cutoff)
        photo_cutoff = _before(months(settings, "photos_months", PHOTOS_MONTHS), now)
        deleted["photos"] += await reports.expire_photos(db, workspace_id, photo_cutoff, BATCH)
        await db.commit()
    # Messages from chats bound to no organization follow the platform default.
    deleted["messages"] += await _delete_messages(db, None, _before(MESSAGES_MONTHS, now))
    await db.commit()
    if any(deleted.values()):
        logger.info("retention: deleted %(messages)d messages, %(photos)d photos", deleted)
    return deleted
