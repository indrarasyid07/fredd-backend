"""Copy a chat's photos and files to Fluctuz storage (roadmap 3.8, CONV-06).

Runs in the worker, only for a chat with an active topic: a stranger's file is never downloaded,
so it never lands under any organization (tenant isolation). The file is checked (size, and that
its bytes really are the kind it claims) before it is stored.

When Telegram or the storage is down the message keeps its `telegram:<file_id>` reference: the
answer is not lost, and the bot's file id stays valid, so the copy can be made later.
"""

import logging
import uuid

from app.core.config import settings
from app.core.storage import get_storage
from app.core.time import now_utc
from app.modules.channels.telegram import BotApi, TelegramError
from app.modules.conversations.models import Message

logger = logging.getLogger(__name__)

MEDIA_KINDS = ("photo", "video", "voice", "document")

# What each kind may really be: (content type, file extension, magic-byte check).
_IMAGES = (
    ("image/jpeg", ".jpg", lambda b: b.startswith(b"\xff\xd8\xff")),
    ("image/png", ".png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
    ("image/webp", ".webp", lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
)
_ALLOWED = {
    "photo": _IMAGES,
    "video": (("video/mp4", ".mp4", lambda b: b[4:8] == b"ftyp"),),
    "voice": (("audio/ogg", ".ogg", lambda b: b.startswith(b"OggS")),),
    "document": (*_IMAGES, ("application/pdf", ".pdf", lambda b: b.startswith(b"%PDF-"))),
}

# Why a file was refused, kept in the message payload for the reply and the activity log.
TOO_LARGE = "too_large"
WRONG_TYPE = "wrong_type"


def sniff(kind: str, data: bytes) -> tuple[str, str] | None:
    """(content type, extension) when the bytes match a type allowed for `kind`."""
    for content_type, ext, matches in _ALLOWED.get(kind, ()):
        if matches(data):
            return content_type, ext
    return None


def object_key(workspace_id: uuid.UUID, message: Message, ext: str) -> str:
    when = message.channel_sent_at or now_utc()
    return f"workspaces/{workspace_id}/messages/{when:%Y/%m}/{message.id}{ext}"


async def store(client: BotApi, message: Message, workspace_id: uuid.UUID) -> bytes | None:
    """Copy the message's file to storage and set `media_key`, or mark why it was refused.
    Returns the bytes stored (a voice note is transcribed from them), None otherwise."""
    file_id = message.payload.get("file_id")
    if message.kind not in MEDIA_KINDS or not file_id or message.media_key:
        return None
    if (message.payload.get("file_size") or 0) > settings.media_max_bytes:
        message.payload = {**message.payload, "media_refused": TOO_LARGE}
        return None
    try:
        data = await client.download_file(str(file_id), settings.media_max_bytes)
    except TelegramError as exc:
        if exc.status == 413:
            message.payload = {**message.payload, "media_refused": TOO_LARGE}
        else:
            logger.warning("telegram file download failed: %s", exc.status)
        return None
    found = sniff(message.kind, data)
    if found is None:
        message.payload = {**message.payload, "media_refused": WRONG_TYPE}
        return None
    content_type, ext = found
    key = object_key(workspace_id, message, ext)
    try:
        await get_storage().put(key, data, content_type)
    except Exception:  # any storage failure: keep the Telegram reference instead
        logger.warning("media storage failed", exc_info=True)
        return None
    message.media_key = key
    message.payload = {**message.payload, "size_bytes": len(data), "content_type": content_type}
    return data
