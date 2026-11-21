"""Joining by code on the shared bot (roadmap 3.6, join-codes.md).

A code from a chat with no topic joins it, then asks "Ya, tetap / Bukan, ganti" with the data
consent sentence. A code from a chat that already has a topic offers "Pindah / Tambah / Batal";
that pending choice lives in Redis for a day. Wrong codes are rate limited per chat identity:
after five in an hour the bot stays silent for that chat.
"""

import json
import re
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import redis
from app.core.time import now_utc
from app.modules.conversations import repository
from app.modules.conversations.engine import copy
from app.modules.conversations.engine.machine import extract_join_code
from app.modules.conversations.engine.parsers import normalize
from app.modules.conversations.engine.types import Button, ConversationState, Outbound
from app.modules.conversations.models import Conversation, Message
from app.modules.extension_workers import service as workers
from app.modules.extension_workers.models import FormAssignment
from app.modules.extension_workers.service import TelegramIdentity
from app.modules.forms import service as forms
from app.modules.join_codes import service as join_codes
from app.modules.join_codes.service import Claimable
from app.modules.workspaces import service as workspaces

MAX_WRONG_CODES = 5
WRONG_CODES_WINDOW = 3600
PENDING_CHOICE_SECONDS = 86400

KEEP, CHANGE = "join:keep", "join:change"
SWITCH, ADD, CANCEL = "join:switch", "join:add", "join:cancel"


@dataclass(frozen=True)
class Chat:
    channel_id: uuid.UUID
    chat_id: str

    @property
    def key(self) -> str:
        return f"{self.channel_id}:{self.chat_id}"


def identity(message: Message) -> TelegramIdentity:
    p = message.payload
    return TelegramIdentity(
        user_id=str(p.get("user_id") or message.chat_id),
        username=p.get("username"),
        name=p.get("name"),
    )


def _first_name(name: str | None) -> str | None:
    return name.split()[0] if name else None


def _looks_like_code(text: str) -> bool:
    """Inside a topic, eight bare letters may be an answer; a code needs its usual shape."""
    t = normalize(text)
    return bool(re.search(r"[\s-]", t)) or t.startswith(("/start", "gabung", "kode"))


async def _wrong_codes(chat: Chat) -> int:
    return int(await redis.get(f"join-wrong:{chat.key}") or 0)


async def _count_wrong_code(chat: Chat) -> int:
    key = f"join-wrong:{chat.key}"
    count = int(await redis.incr(key))
    if count == 1:
        await redis.expire(key, WRONG_CODES_WINDOW)
    return count


async def is_silenced(chat: Chat) -> bool:
    return await _wrong_codes(chat) >= MAX_WRONG_CODES


# --- Entry point --------------------------------------------------------------------------------


async def route(db: AsyncSession, chat: Chat, message: Message) -> list[Outbound] | None:
    """Replies when the message is about joining; None when it is not (the report flow's)."""
    if message.kind == "button" and (message.body or "").startswith("join:"):
        return await _button(db, chat, message, message.body or "")
    text = message.body if message.kind == "text" else None
    code = extract_join_code(text)
    current = await workers.active_assignment(db, chat.channel_id, chat.chat_id)
    if code and text and (current is None or _looks_like_code(text)):
        if await is_silenced(chat):
            return []
        return await claim(db, chat, message, code, current)
    if current is not None:
        return None
    # A chat with no topic: never creates anything in any organization.
    if await is_silenced(chat):
        return []
    if message.payload.get("edited"):
        return [Outbound(copy.EDITED)]
    pending = await workers.pending_worker(db, identity(message).user_id)
    if pending is not None:
        return [
            Outbound(copy.waiting_approval(await workspaces.get_name(db, pending.workspace_id)))
        ]
    return [Outbound(copy.JOIN_FIRST)]


async def claim(
    db: AsyncSession,
    chat: Chat,
    message: Message,
    code: str,
    current: FormAssignment | None,
) -> list[Outbound]:
    found = await join_codes.find_claimable(db, code)
    if found == "unknown":
        count = await _count_wrong_code(chat)
        return [Outbound(copy.CODE_UNKNOWN)] if count <= MAX_WRONG_CODES else []
    if found == "closed":
        return [Outbound(copy.CODE_CLOSED)]
    if found == "not_open":
        return [Outbound(copy.topic_not_open("Topik ini"))]
    assert isinstance(found, Claimable)

    who = identity(message)
    existing = await workers.get_worker(db, found.join_code.workspace_id, who)
    if existing is not None and existing.status == "blocked":
        return [Outbound(copy.CODE_CLOSED)]  # never tell a blocked person why

    if current is not None:
        if current.form_id == found.form_id:
            return [Outbound(copy.already_joined(found.organization, found.form_name))]
        await redis.set(
            f"join-choice:{chat.key}",
            json.dumps({"code": code}),
            ex=PENDING_CHOICE_SECONDS,
        )
        buttons = (
            Button(copy.switch_to(found.form_name), SWITCH),
            Button(copy.ADD_TOPIC, ADD),
            Button(copy.CANCEL, CANCEL),
        )
        return [Outbound(copy.switch_or_add(found.organization, found.form_name), buttons=buttons)]

    joined = await _join(db, chat, found, who, confirm=True)
    if joined is None:
        return [Outbound(copy.CODE_CLOSED)]
    if joined.pending_approval:
        return [Outbound(copy.waiting_approval(found.organization))]
    return [
        Outbound(
            copy.joined(
                _first_name(who.name),
                found.organization,
                found.form_name,
                settings.privacy_policy_url,
            ),
            buttons=(Button(copy.KEEP, KEEP), Button(copy.NOT_MINE, CHANGE)),
        )  # fmt: skip
    ]


async def _join(
    db: AsyncSession, chat: Chat, found: Claimable, who: TelegramIdentity, *, confirm: bool
) -> workers.Joined | None:
    now = now_utc()
    if not await join_codes.take_use(db, found.join_code.id, now):
        return None  # filled up or closed a moment ago
    joined = await workers.join(
        db,
        workspace_id=found.join_code.workspace_id,
        form_id=found.form_id,
        join_code_id=found.join_code.id,
        manual_approval=found.join_code.approval_mode == "manual",
        identity=who,
        now=now,
    )
    conversation = await repository.get_conversation(db, joined.worker.id, found.form_id)
    if conversation is None:
        conversation = Conversation(
            workspace_id=found.join_code.workspace_id,
            extension_worker_id=joined.worker.id,
            form_id=found.form_id,
            channel_id=chat.channel_id,
            chat_id=chat.chat_id,
        )
        db.add(conversation)
    status = "joining" if confirm else "idle"
    conversation.channel_id, conversation.chat_id = chat.channel_id, chat.chat_id
    conversation.status = status
    conversation.state = ConversationState(status=status, topic_id=str(found.form_id)).to_json()
    conversation.last_inbound_at = now
    if not joined.pending_approval:
        await workers.set_active(db, chat.channel_id, chat.chat_id, joined.assignment.id)
    await db.flush()
    return joined


# --- Buttons ------------------------------------------------------------------------------------


async def _button(db: AsyncSession, chat: Chat, message: Message, value: str) -> list[Outbound]:
    if value in (KEEP, CHANGE):
        return await _confirm(db, chat, value == KEEP)
    choice = await redis.getdel(f"join-choice:{chat.key}")
    if value == CANCEL:
        return [Outbound(copy.CANCELLED)]
    if choice is None:
        return [Outbound(copy.CHOICE_EXPIRED)]
    found = await join_codes.find_claimable(db, json.loads(choice)["code"])
    if not isinstance(found, Claimable):
        return [Outbound(copy.CODE_CLOSED)]
    current = await workers.active_assignment(db, chat.channel_id, chat.chat_id)
    joined = await _join(db, chat, found, identity(message), confirm=False)
    if joined is None:
        return [Outbound(copy.CODE_CLOSED)]
    if value == SWITCH and current is not None and current.form_id != found.form_id:
        await workers.leave(db, current, now_utc())
    if joined.pending_approval:
        return [Outbound(copy.waiting_approval(found.organization))]
    url = settings.privacy_policy_url
    return [Outbound(copy.switched(found.organization, found.form_name, url))]


async def _confirm(db: AsyncSession, chat: Chat, keep: bool) -> list[Outbound]:
    current = await workers.active_assignment(db, chat.channel_id, chat.chat_id)
    conversation = (
        await repository.get_conversation(db, current.extension_worker_id, current.form_id)
        if current is not None
        else None
    )
    if current is None or conversation is None or conversation.status != "joining":
        return [Outbound(copy.CHOICE_EXPIRED)]  # an old message's buttons
    conversation.status = "idle"
    conversation.state = ConversationState(status="idle", topic_id=str(current.form_id)).to_json()
    if keep:
        worker = await workers.get_by_id(db, current.extension_worker_id)
        if worker is not None:
            worker.confirmed_at = now_utc()
        form = await forms.get_form(db, current.workspace_id, current.form_id)
        voice = (form.settings or {}).get("input_mode") == "voice"
        return [Outbound(copy.AFTER_KEEP_VOICE if voice else copy.AFTER_KEEP)]
    await workers.leave(db, current, now_utc())
    await workers.set_active(db, chat.channel_id, chat.chat_id, None)
    return [Outbound(copy.AFTER_CHANGE)]
