"""Telegram Bot API adapter (B-048 shared bot): read webhook updates, send messages.

Parsing is pure (`parse_update`) so it is tested against fixture payloads. `TelegramClient`
calls the Bot API over httpx; it never logs or raises with the request URL, which carries the
token.
"""

import html
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import httpx

from app.core.config import settings
from app.modules.conversations.engine.types import Outbound

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"
CALLBACK_DATA_MAX_BYTES = 64
LOCATION_BUTTON = "📍 Kirim lokasi"

Kind = Literal["text", "button", "location", "photo", "video", "voice", "document", "other"]


@dataclass(frozen=True)
class InboundUpdate:
    """One update worth storing: a private-chat message or a button tap."""

    update_id: int
    chat_id: str
    kind: Kind
    sent_at: datetime
    body: str | None = None
    # Kind-specific details kept in `messages.payload` (file id, coordinates, callback id...).
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def external_id(self) -> str:
        return f"update:{self.update_id}"


@dataclass(frozen=True)
class LeaveGroup:
    """The bot was added to a group or channel: it only works in private chats (3.5a)."""

    chat_id: str


@dataclass(frozen=True)
class BotBlocked:
    """The user blocked the bot (`my_chat_member` → kicked)."""

    chat_id: str


Parsed = InboundUpdate | LeaveGroup | BotBlocked | None


def _when(unix: int | None) -> datetime:
    return datetime.fromtimestamp(unix, UTC) if unix else datetime.now(UTC)


def _sender(message: dict[str, Any]) -> dict[str, Any]:
    user = message.get("from") or {}
    return {
        "user_id": str(user["id"]) if "id" in user else None,
        "username": user.get("username"),
        "name": " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p) or None,
    }


def parse_update(update: dict[str, Any]) -> Parsed:
    """Telegram update → what to store, or None to ignore it. Never raises on odd payloads."""
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        return None

    if member := update.get("my_chat_member"):
        chat = member.get("chat") or {}
        status = (member.get("new_chat_member") or {}).get("status")
        if chat.get("type") == "private":
            return BotBlocked(str(chat["id"])) if status == "kicked" else None
        if status in ("member", "administrator") and "id" in chat:
            return LeaveGroup(str(chat["id"]))
        return None

    if callback := update.get("callback_query"):
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        if chat.get("type") != "private" or "data" not in callback:
            return None
        return InboundUpdate(
            update_id=update_id, chat_id=str(chat["id"]), kind="button", sent_at=_when(None),
            body=str(callback["data"]),
            payload={"callback_id": callback.get("id"), "message_id": message.get("message_id"),
                     **_sender(callback)},
        )  # fmt: skip

    edited = update.get("edited_message")
    message = update.get("message") or edited
    if not message:
        return None  # channel posts, polls, inline queries...
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return None
    chat_id = str(chat["id"])
    base = {"message_id": message.get("message_id"), **_sender(message)}
    sent_at = _when(message.get("date"))

    if edited:
        # A moving live location arrives as edits: only its first position counts (3.5a).
        if "location" in edited:
            return None
        return InboundUpdate(update_id, chat_id, "other", sent_at,
                             payload={**base, "edited": True})  # fmt: skip

    caption = message.get("caption")
    if group := message.get("media_group_id"):
        base["media_group_id"] = str(group)
    if text := message.get("text"):
        return InboundUpdate(update_id, chat_id, "text", sent_at, body=text, payload=base)
    if loc := message.get("location"):
        payload = {**base, "lat": loc.get("latitude"), "lng": loc.get("longitude"),
                   "accuracy_m": loc.get("horizontal_accuracy"),
                   "live": "live_period" in loc}  # fmt: skip
        return InboundUpdate(update_id, chat_id, "location", sent_at, payload=payload)
    if photos := message.get("photo"):
        largest = max(photos, key=lambda p: p.get("file_size") or p.get("width", 0))
        payload = {**base, "file_id": largest.get("file_id"),
                   "file_unique_id": largest.get("file_unique_id")}  # fmt: skip
        return InboundUpdate(update_id, chat_id, "photo", sent_at, body=caption, payload=payload)
    for kind in ("video", "voice", "document"):
        if media := message.get(kind):
            payload = {
                **base,
                "file_id": media.get("file_id"),
                "mime_type": media.get("mime_type"),
                "duration": media.get("duration"),
            }
            return InboundUpdate(update_id, chat_id, kind, sent_at, body=caption, payload=payload)
    # Stickers, contacts, polls, games...
    kind_name = next(
        (k for k in ("sticker", "contact", "poll", "animation", "audio") if k in message), "unknown"
    )
    return InboundUpdate(update_id, chat_id, "other", sent_at, payload={**base, "type": kind_name})


# --- Sending ------------------------------------------------------------------------------------


def render_html(text: str) -> str:
    """Engine text (`*bold*` marks recorded values) → Telegram HTML, everything else escaped."""
    return re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", html.escape(text, quote=False))


def reply_markup(out: Outbound) -> dict[str, Any] | None:
    if out.buttons:
        for b in out.buttons:
            if len(b.value.encode()) > CALLBACK_DATA_MAX_BYTES:
                raise ValueError(f"callback_data over {CALLBACK_DATA_MAX_BYTES} bytes: {b.value!r}")
        buttons = [{"text": b.label, "callback_data": b.value} for b in out.buttons]
        # Short yes/no style answers share a row; anything longer gets its own row.
        if len(buttons) <= 3 and all(len(b.label) <= 14 for b in out.buttons):
            return {"inline_keyboard": [buttons]}
        return {"inline_keyboard": [[b] for b in buttons]}
    if out.ask_location:
        return {
            "keyboard": [[{"text": LOCATION_BUTTON, "request_location": True}]],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        }
    return None


class TelegramError(Exception):
    """A Bot API call failed. `status` is Telegram's error_code (403 = blocked by the user), or
    None when the request never got an answer."""

    def __init__(self, status: int | None, description: str, *, timed_out: bool = False) -> None:
        super().__init__(f"telegram {status}: {description}")
        self.status = status
        self.description = description
        self.timed_out = timed_out


class BotApi(Protocol):
    """What the chat pipeline needs from a bot: the real client, the devtools stand-in, or a
    test fake."""

    async def send(self, chat_id: str, out: Outbound) -> str: ...
    async def answer_callback(self, callback_id: str) -> None: ...
    async def leave_chat(self, chat_id: str) -> None: ...


class TelegramClient:
    def __init__(self, token: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(
            base_url=f"{API}/bot{token}/", timeout=httpx.Timeout(10.0, connect=5.0),
            transport=transport,
        )  # fmt: skip

    async def aclose(self) -> None:
        await self._http.aclose()

    async def call(self, method: str, **params: Any) -> Any:
        try:
            response = await self._http.post(method, json=params)
        except httpx.TimeoutException:
            # Telegram may or may not have delivered it (roadmap 3.9a: "uncertain").
            raise TelegramError(None, "timeout", timed_out=True) from None
        except httpx.HTTPError as exc:
            raise TelegramError(None, type(exc).__name__) from None
        try:
            data = response.json()
        except ValueError:
            raise TelegramError(response.status_code, "invalid response") from None
        if not data.get("ok"):
            raise TelegramError(data.get("error_code", response.status_code),
                                str(data.get("description", ""))[:200])  # fmt: skip
        return data.get("result")

    async def send(self, chat_id: str, out: Outbound) -> str:
        """Send one engine message; returns Telegram's message id."""
        params: dict[str, Any] = {"chat_id": chat_id, "text": render_html(out.text),
                                  "parse_mode": "HTML"}  # fmt: skip
        if (markup := reply_markup(out)) is not None:
            params["reply_markup"] = markup
        result = await self.call("sendMessage", **params)
        return str(result["message_id"])

    async def get_updates(self, offset: int | None, wait_seconds: int) -> list[dict[str, Any]]:
        """Long polling for development bots (no public URL needed)."""
        params: dict[str, Any] = {
            "timeout": wait_seconds,
            "allowed_updates": ["message", "edited_message", "callback_query", "my_chat_member"],
        }
        if offset is not None:
            params["offset"] = offset
        try:
            response = await self._http.post(
                "getUpdates", json=params, timeout=httpx.Timeout(wait_seconds + 10.0, connect=5.0)
            )
        except httpx.TimeoutException:
            return []
        except httpx.HTTPError as exc:
            raise TelegramError(None, type(exc).__name__) from None
        data = response.json()
        if not data.get("ok"):
            raise TelegramError(data.get("error_code"), str(data.get("description", ""))[:200])
        return list(data.get("result") or [])

    async def answer_callback(self, callback_id: str) -> None:
        # Stops the button's loading spinner; Telegram wants it within seconds.
        await self.call("answerCallbackQuery", callback_query_id=callback_id)

    async def leave_chat(self, chat_id: str) -> None:
        await self.call("leaveChat", chat_id=chat_id)


_client: TelegramClient | None = None


def get_client() -> TelegramClient:
    """The process-wide client (one connection pool). Tests replace it."""
    global _client
    if _client is None:
        _client = TelegramClient(settings.telegram_bot_token)
    return _client
