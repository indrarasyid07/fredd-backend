"""Constraints the chat pipeline relies on (roadmap 3.4), against the real database."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.channels.models import Channel
from app.modules.conversations.models import Conversation, Message
from app.modules.extension_workers.models import ChatContext, ExtensionWorker, FormAssignment
from app.modules.forms import service as forms
from app.modules.forms.schemas import FormDefinition
from app.modules.workspaces.models import Workspace
from tests.form_definitions import crop_survey


async def _telegram(db: AsyncSession) -> Channel:
    channel = Channel(type="telegram", display_name="Fluctuz", bot_username="FluctuzBot")
    db.add(channel)
    await db.flush()
    return channel


async def _expect_conflict(db: AsyncSession, row: object) -> None:
    async with db.begin_nested():
        db.add(row)
        with pytest.raises(IntegrityError):
            await db.flush()


async def test_one_platform_bot_per_type(db: AsyncSession) -> None:
    await _telegram(db)
    await _expect_conflict(db, Channel(type="telegram", display_name="Lain"))


async def test_same_update_is_stored_once(db: AsyncSession) -> None:
    channel = await _telegram(db)

    def message() -> Message:
        return Message(
            channel_id=channel.id, chat_id="111", direction="in", kind="text", body="halo",
            external_id="update:42",
        )  # fmt: skip

    db.add(message())
    await db.flush()
    await _expect_conflict(db, message())


async def test_unbound_chat_messages_belong_to_no_organization(db: AsyncSession) -> None:
    channel = await _telegram(db)
    db.add(Message(channel_id=channel.id, chat_id="999", direction="in", kind="text", body="halo"))
    await db.flush()  # no workspace, no conversation: allowed


async def test_one_worker_per_organization_and_identity(
    db: AsyncSession, organization: Workspace
) -> None:
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    db.add(ExtensionWorker(workspace_id=organization.id, name="Budi", telegram_user_id="111"))
    db.add(ExtensionWorker(workspace_id=other.id, name="Budi", telegram_user_id="111"))
    await db.flush()  # the same person in two organizations: two rows
    await _expect_conflict(
        db, ExtensionWorker(workspace_id=organization.id, name="Budi 2", telegram_user_id="111")
    )
    await _expect_conflict(db, ExtensionWorker(workspace_id=organization.id, name="Tanpa"))


async def test_one_assignment_and_conversation_per_worker_and_topic(
    db: AsyncSession, organization: Workspace
) -> None:
    channel = await _telegram(db)
    form = await forms.create_form(
        db, organization.id, None, "Survei", FormDefinition.model_validate(crop_survey())
    )
    worker = ExtensionWorker(workspace_id=organization.id, name="Budi", telegram_user_id="111")
    db.add(worker)
    await db.flush()

    db.add(
        FormAssignment(workspace_id=organization.id, extension_worker_id=worker.id, form_id=form.id)
    )
    await db.flush()
    await _expect_conflict(
        db,
        FormAssignment(
            workspace_id=organization.id, extension_worker_id=worker.id, form_id=form.id
        ),
    )

    def conversation() -> Conversation:
        return Conversation(
            workspace_id=organization.id, extension_worker_id=worker.id, form_id=form.id,
            channel_id=channel.id, chat_id="111",
        )  # fmt: skip

    db.add(conversation())
    await db.flush()
    await _expect_conflict(db, conversation())


async def test_one_routing_row_per_chat(db: AsyncSession) -> None:
    channel = await _telegram(db)
    db.add(ChatContext(channel_id=channel.id, chat_id="111"))
    await db.flush()
    await _expect_conflict(db, ChatContext(channel_id=channel.id, chat_id="111"))
