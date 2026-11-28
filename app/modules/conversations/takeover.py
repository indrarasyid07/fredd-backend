"""An admin answers a chat instead of Fluctuz (roadmap 6.4).

Take over with one conditional UPDATE (two admins: one wins, the other gets 409); only the admin
who took it over writes; any admin hands it back, and a takeover with no admin reply for
`AUTO_RELEASE_AFTER` comes back on its own. While taken over the worker's messages are stored and
shown, and the bot stays quiet (`service.deliver` checks again right before sending).
"""

import logging
import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.activity import service as activity
from app.modules.audit import service as audit
from app.modules.auth.models import User
from app.modules.channels.models import Channel
from app.modules.conversations import inbox, repository
from app.modules.conversations.engine import machine
from app.modules.conversations.engine.types import ConversationState
from app.modules.conversations.errors import (
    ConversationNotFound,
    ConversationNotTakenOver,
    ConversationTakenOver,
    NotTakenOverByYou,
    WhatsAppWindowClosed,
)
from app.modules.conversations.models import Conversation, Message
from app.modules.conversations.schemas import ConversationDetailOut
from app.modules.forms import service as forms
from app.modules.forms.errors import FormVersionNotFound
from app.modules.forms.models import Form
from app.modules.workspaces.service import ActiveMember

logger = logging.getLogger(__name__)

# Decided 28 Nov 2026: 4 hours without an admin reply, then Fluctuz carries on (log only).
AUTO_RELEASE_AFTER = timedelta(hours=4)


async def _event(db: AsyncSession, conversation: Conversation, type: str, admin: str) -> None:
    channel = await db.get(Channel, conversation.channel_id)
    form = await db.get(Form, conversation.form_id)
    await activity.record(
        db,
        workspace_id=conversation.workspace_id,
        type=type,
        status="done",
        channel=channel.type if channel else None,
        extension_worker_id=conversation.extension_worker_id,
        conversation_id=conversation.id,
        details={"admin_name": admin, "form_name": form.name if form else ""},
    )


async def take_over(
    db: AsyncSession, member: ActiveMember, conversation_id: uuid.UUID
) -> ConversationDetailOut:
    won = await repository.take_over(
        db, member.workspace_id, conversation_id, member.member.user_id
    )
    if not won:
        conversation = await repository.lock_conversation(db, member.workspace_id, conversation_id)
        if conversation is None:
            raise ConversationNotFound()
        if conversation.taken_over_by_user_id == member.member.user_id:
            return await inbox.get_conversation(db, member, conversation_id)  # already yours
        holder = await db.get(User, conversation.taken_over_by_user_id)
        raise ConversationTakenOver(
            f"Percakapan ini sudah ditangani {holder.name}." if holder else None
        )
    conversation = await repository.lock_conversation(db, member.workspace_id, conversation_id)
    assert conversation is not None
    name = await _name(db, member.member.user_id)
    await audit.record(
        db,
        workspace_id=member.workspace_id,
        actor_user_id=member.member.user_id,
        action="conversation.taken_over",
        target=f"conversation:{conversation_id}",
    )
    await _event(db, conversation, "taken_over", name)
    await db.commit()
    return await inbox.get_conversation(db, member, conversation_id)


async def send_message(
    db: AsyncSession, member: ActiveMember, conversation_id: uuid.UUID, text: str
) -> uuid.UUID:
    """Store the admin's reply as a pending outbound row; the caller queues its delivery."""
    conversation = await repository.lock_conversation(db, member.workspace_id, conversation_id)
    if conversation is None:
        raise ConversationNotFound()
    if conversation.taken_over_by_user_id != member.member.user_id:
        raise NotTakenOverByYou()
    channel = await db.get(Channel, conversation.channel_id)
    expires = inbox.whatsapp_window_expires_at(
        channel.type if channel else "", conversation.last_inbound_at
    )
    if (
        channel is not None
        and channel.type == "whatsapp"
        and (expires is None or expires <= now_utc())
    ):
        raise WhatsAppWindowClosed()
    message = Message(
        workspace_id=conversation.workspace_id,
        conversation_id=conversation.id,
        channel_id=conversation.channel_id,
        chat_id=conversation.chat_id,
        direction="out",
        kind="text",
        body=text.strip(),
        payload={
            "buttons": [],
            "ask_location": False,
            "admin_user_id": str(member.member.user_id),
            "admin_name": await _name(db, member.member.user_id),
        },
        delivery_status="pending",
    )
    db.add(message)
    await db.commit()
    return message.id


async def release(
    db: AsyncSession, member: ActiveMember, conversation_id: uuid.UUID
) -> tuple[ConversationDetailOut, list[uuid.UUID]]:
    """Hand the chat back to Fluctuz; returns the conversation and the bot replies to send."""
    conversation = await repository.lock_conversation(db, member.workspace_id, conversation_id)
    if conversation is None:
        raise ConversationNotFound()
    if conversation.taken_over_by_user_id is None:
        raise ConversationNotTakenOver()
    to_send = await _hand_back(db, conversation)
    await audit.record(
        db,
        workspace_id=member.workspace_id,
        actor_user_id=member.member.user_id,
        action="conversation.released",
        target=f"conversation:{conversation_id}",
    )
    await _event(db, conversation, "released", await _name(db, member.member.user_id))
    await db.commit()
    return await inbox.get_conversation(db, member, conversation_id), to_send


async def release_stale(db: AsyncSession) -> list[uuid.UUID]:
    """Cron: takeovers whose admin wrote nothing for `AUTO_RELEASE_AFTER` come back to Fluctuz,
    with a line in the activity log (the admin's notification)."""
    to_send: list[uuid.UUID] = []
    for conversation in await repository.list_stale_takeovers(db, now_utc() - AUTO_RELEASE_AFTER):
        admin = await _name(db, conversation.taken_over_by_user_id)
        to_send += await _hand_back(db, conversation)
        await _event(db, conversation, "auto_released", admin)
        logger.info("takeover of conversation %s released automatically", conversation.id)
    await db.commit()
    return to_send


async def _hand_back(db: AsyncSession, conversation: Conversation) -> list[uuid.UUID]:
    definition = None
    if conversation.form_version_id is not None:
        try:
            definition = (
                await forms.get_version_definition(
                    db, conversation.workspace_id, conversation.form_version_id
                )
            ).definition
        except FormVersionNotFound:
            definition = None
    step = machine.resume(ConversationState.from_json(conversation.state), definition)
    conversation.state = step.state.to_json()
    conversation.status = step.state.status
    conversation.step = step.state.step
    conversation.failed_attempts = 0
    conversation.taken_over_by_user_id = None
    conversation.taken_over_at = None
    replies = [
        Message(
            workspace_id=conversation.workspace_id,
            conversation_id=conversation.id,
            channel_id=conversation.channel_id,
            chat_id=conversation.chat_id,
            direction="out",
            kind="text",
            body=reply.text,
            payload={
                "buttons": [{"label": b.label, "value": b.value} for b in reply.buttons],
                "ask_location": reply.ask_location,
            },
            delivery_status="pending",
        )
        for reply in step.replies
    ]
    db.add_all(replies)
    await db.flush()
    return [m.id for m in replies]


async def _name(db: AsyncSession, user_id: uuid.UUID | None) -> str:
    user = await db.get(User, user_id) if user_id is not None else None
    return user.name if user is not None else "Admin"
