"""Chat simulator: talk to the real conversation pipeline from a browser, no Telegram needed.

Each message is shaped like a Telegram update and goes through the webhook's path: stored once,
processed, replies recorded as outbound messages. Only the Bot API is replaced (replies are
marked sent, not delivered anywhere). Writes to the configured database like the real bot.
"""

import base64
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.redis import redis
from app.core.time import now_utc
from app.modules.ai.speech import fake_voice_note
from app.modules.channels import service as channels
from app.modules.conversations import service
from app.modules.conversations.engine.types import Outbound
from app.modules.conversations.models import Message

router = APIRouter(prefix="/devtools", include_in_schema=False)
PAGE = Path(__file__).with_name("chat.html")


TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////"
    "////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
)


# Words of simulated voice notes by file id, until the pipeline "downloads" them.
SPOKEN: dict[str, str] = {}


class DevtoolsTelegram:
    """Stands in for the Bot API: every send succeeds and goes nowhere."""

    async def send(self, chat_id: str, out: Outbound) -> str:
        return f"dev-{uuid.uuid4().hex[:12]}"

    async def answer_callback(self, callback_id: str) -> None:
        return None

    async def leave_chat(self, chat_id: str) -> None:
        return None

    async def download_file(self, file_id: str, max_bytes: int) -> bytes:
        # A simulated voice note carries its words; a 1x1 JPEG stands in for any photo. Either
        # way the simulator exercises the storage too.
        if said := SPOKEN.pop(file_id, None):
            return fake_voice_note(said)
        return TINY_JPEG


class SimulatedLocation(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=10, ge=0)


class SimulatedMessage(BaseModel):
    chat_id: str = Field(default="devtools-1", pattern=r"^devtools-[A-Za-z0-9_-]{1,40}$")
    name: str = Field(default="Budi Santoso", max_length=60)
    text: str | None = Field(default=None, max_length=4000)
    button: str | None = Field(default=None, max_length=64)
    # A shared location or a photo instead of text (roadmap 3.7: report fields).
    location: SimulatedLocation | None = None
    photo: bool = False
    # A voice note: these are the words the fake speech provider "hears" (Voice Lab).
    voice: str | None = Field(default=None, max_length=1000)


def _update(update_id: int, msg: SimulatedMessage, now: int) -> dict[str, Any]:
    first, _, last = msg.name.partition(" ")
    user = {"id": msg.chat_id, "is_bot": False, "first_name": first, "last_name": last or None}
    chat = {"id": msg.chat_id, "type": "private", "first_name": first}
    if msg.button is not None:
        return {
            "update_id": update_id,
            "callback_query": {
                "id": f"devtools-{update_id}", "from": user, "data": msg.button,
                "message": {"message_id": 0, "chat": chat, "date": now},
            },
        }  # fmt: skip
    message: dict[str, Any] = {"message_id": update_id, "from": user, "chat": chat, "date": now}
    if msg.location is not None:
        message["location"] = {"latitude": msg.location.lat, "longitude": msg.location.lng,
                               "horizontal_accuracy": msg.location.accuracy_m}  # fmt: skip
    elif msg.voice is not None:
        file_id = f"devtools-voice-{update_id}"
        SPOKEN[file_id] = msg.voice
        message["voice"] = {"file_id": file_id, "duration": 4, "mime_type": "audio/ogg"}
    elif msg.photo:
        # A made-up file reference; "downloading" it gives TINY_JPEG.
        message["photo"] = [{"file_id": f"devtools-photo-{update_id}",
                             "file_unique_id": f"devtools-{update_id}", "width": 1280}]  # fmt: skip
    else:
        message["text"] = msg.text or ""
    return {"update_id": update_id, "message": message}


def _shown(message: Message) -> str:
    """What a message without text stands for in the simulator's history."""
    if message.kind == "location":
        return f"📍 {message.payload.get('lat')}, {message.payload.get('lng')}"
    if message.kind == "photo":
        return "📷 (foto)"
    if message.kind == "voice":
        heard = message.payload.get("transcript")
        return f'🎤 "{heard}"' if heard else "🎤 (pesan suara)"
    return f"({message.kind})"


def _out(message: Message) -> dict[str, Any]:
    return {
        "direction": message.direction,
        "text": message.body or _shown(message),
        "buttons": message.payload.get("buttons", []),
        "workspace_id": str(message.workspace_id) if message.workspace_id else None,
        "at": message.created_at.isoformat() if message.created_at else None,
    }


@router.get("", response_class=HTMLResponse)
async def page() -> HTMLResponse:
    return HTMLResponse(PAGE.read_text())


@router.post("/telegram/messages")
async def send(
    msg: SimulatedMessage, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, Any]:
    """Send one simulated message; returns the bot's replies."""
    update_id = 900_000_000 + int(await redis.incr("devtools:update-id"))
    received = await service.receive_telegram(
        db, _update(update_id, msg, int(now_utc().timestamp()))
    )
    client = DevtoolsTelegram()
    replies: list[dict[str, Any]] = []
    for message_id in received.deliver:
        await service.deliver(db, client, message_id)
    if received.deliver:
        channel = await channels.telegram_channel(db)
        replies = [_out(m) for m in await service.chat_history(db, channel.id, msg.chat_id)
                   if m.id in received.deliver]  # fmt: skip
    if received.process is not None:
        channel_id, chat_id = received.process
        sent = await service.process_chat(db, client, channel_id, chat_id)
        for message_id in sent:
            await service.deliver(db, client, message_id)
        replies = [_out(m) for m in await service.chat_history(db, channel_id, chat_id)
                   if m.id in sent]  # fmt: skip
    return {"replies": replies}


@router.get("/telegram/{chat_id}/messages")
async def history(chat_id: str, db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, Any]:
    channel = await channels.telegram_channel(db)
    rows = await service.chat_history(db, channel.id, chat_id)
    return {"messages": [_out(m) for m in rows]}
