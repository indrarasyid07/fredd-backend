"""Joining by code on the shared Telegram bot (roadmap 3.6, join-codes.md)."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.audit.models import AuditLog
from app.modules.conversations.engine import copy
from app.modules.conversations.models import Conversation, Message
from app.modules.extension_workers.models import ChatContext, ExtensionWorker, FormAssignment
from app.modules.forms import service as forms
from app.modules.forms.models import Form, FormVersion
from app.modules.forms.schemas import FormDefinition
from app.modules.join_codes import repository as join_code_repo
from app.modules.join_codes.models import JoinCode
from app.modules.workspaces.models import Workspace
from tests.form_definitions import crop_survey
from tests.telegram_fixtures import FakeTelegram, post_update, telegram_update

CHAT = "700100200"


class Chat:
    """Budi's private chat with the bot."""

    def __init__(self, client: AsyncClient, bot: FakeTelegram) -> None:
        self.client, self.bot, self.next_id = client, bot, 520000000

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    async def say(self, text: str) -> list[str]:
        update = telegram_update("text", update_id=self._id())
        update["message"]["text"] = text
        update["message"]["date"] += self.next_id  # later messages, later dates
        return await self._send(update)

    async def tap(self, value: str) -> list[str]:
        update = telegram_update("callback", update_id=self._id())
        update["callback_query"]["data"] = value
        return await self._send(update)

    async def _send(self, update: dict[str, Any]) -> list[str]:
        before = len(self.bot.sent)
        assert await post_update(self.client, update) == 200
        return [out.text for _, out in self.bot.sent[before:]]

    def buttons(self) -> list[str]:
        return [b.value for b in self.bot.sent[-1][1].buttons]


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> Chat:
    return Chat(client, bot)


async def _topic(
    db: AsyncSession, workspace: Workspace, name: str = "Survei Tanaman", status: str = "active"
) -> JoinCode:
    form = await forms.create_form(
        db, workspace.id, None, name, FormDefinition.model_validate(crop_survey())
    )
    row = await db.get(Form, form.id)
    assert row is not None
    row.status = status
    if status in ("pilot", "active"):
        # Open structures always run on a published version.
        version = await db.scalar(select(FormVersion).where(FormVersion.form_id == form.id))
        assert version is not None
        version.published_at = now_utc()
        row.current_version_id = version.id
    code = await join_code_repo.get_live_for_form(db, workspace.id, form.id)
    assert code is not None
    await db.flush()
    return code


def _dashed(code: JoinCode) -> str:
    return f"{code.code[:4]}-{code.code[4:]}"


async def _count(db: AsyncSession, model: type) -> int:
    return await db.scalar(select(func.count()).select_from(model)) or 0


async def _worker(db: AsyncSession, workspace: Workspace) -> ExtensionWorker:
    worker = await db.scalar(
        select(ExtensionWorker).where(ExtensionWorker.workspace_id == workspace.id)
    )
    assert worker is not None
    await db.refresh(worker)
    return worker


async def test_start_link_joins_and_asks_to_confirm(
    chat: Chat, db: AsyncSession, organization: Workspace
) -> None:
    code = await _topic(db, organization)
    (reply,) = await chat.say(f"/start {code.code}")
    assert reply.startswith("Halo Budi! Anda bergabung di *")
    assert f"{organization.name} · Survei Tanaman" in reply
    assert "pengendali data" in reply
    assert chat.buttons() == ["join:keep", "join:change"]

    worker = await _worker(db, organization)
    assert (worker.name, worker.telegram_user_id, worker.status) == ("Budi Santoso", CHAT, "active")
    assert worker.telegram_username == "budi_tani"
    assignment = await db.scalar(select(FormAssignment))
    context = await db.scalar(select(ChatContext))
    assert assignment is not None and context is not None
    assert context.active_assignment_id == assignment.id
    conversation = await db.scalar(select(Conversation))
    assert conversation is not None and conversation.status == "joining"
    await db.refresh(code)
    assert code.use_count == 1
    assert (
        await db.scalar(select(func.count()).where(AuditLog.action == "extension_worker.joined"))
        == 1
    )


async def test_keep_confirms_the_topic(
    chat: Chat, db: AsyncSession, organization: Workspace
) -> None:
    code = await _topic(db, organization)
    await chat.say(_dashed(code))
    assert await chat.tap("join:keep") == [copy.AFTER_KEEP]
    worker = await _worker(db, organization)
    assert worker.confirmed_at is not None
    conversation = await db.scalar(select(Conversation))
    assert conversation is not None and conversation.status == "idle"
    # An old confirmation button does nothing more.
    assert await chat.tap("join:change") == [copy.CHOICE_EXPIRED]


async def test_not_mine_undoes_the_join(
    chat: Chat, db: AsyncSession, organization: Workspace
) -> None:
    code = await _topic(db, organization)
    await chat.say(f"gabung {code.code.lower()}")
    assert await chat.tap("join:change") == [copy.AFTER_CHANGE]
    assignment = await db.scalar(select(FormAssignment))
    assert assignment is not None and assignment.status == "left"
    assert (await _worker(db, organization)).status == "left"
    assert await chat.say("halo") == [copy.JOIN_FIRST]  # no topic any more


async def test_unknown_code_creates_nothing_and_goes_silent_after_five(
    chat: Chat, db: AsyncSession
) -> None:
    for _ in range(5):
        assert await chat.say("ABCD-EFGH") == [copy.CODE_UNKNOWN]
    assert await chat.say("ABCD-EFGJ") == []
    assert await chat.say("halo") == []  # silent for that chat for the hour
    for model in (ExtensionWorker, FormAssignment, Conversation, ChatContext):
        assert await _count(db, model) == 0


@pytest.mark.parametrize(
    ("change", "reply"),
    [
        ({"status": "paused"}, copy.CODE_CLOSED),
        ({"max_uses": 1, "use_count": 1}, copy.CODE_CLOSED),
    ],
)
async def test_closed_codes(
    chat: Chat, db: AsyncSession, organization: Workspace, change: dict[str, Any], reply: str
) -> None:
    code = await _topic(db, organization)
    for key, value in change.items():
        setattr(code, key, value)
    await db.flush()
    assert await chat.say(_dashed(code)) == [reply]
    assert await _count(db, ExtensionWorker) == 0


async def test_draft_topic_is_not_open_yet(
    chat: Chat, db: AsyncSession, organization: Workspace
) -> None:
    code = await _topic(db, organization, status="draft")
    assert await chat.say(_dashed(code)) == [copy.topic_not_open("Topik ini")]
    assert await _count(db, ExtensionWorker) == 0


async def test_manual_approval_waits(chat: Chat, db: AsyncSession, organization: Workspace) -> None:
    code = await _topic(db, organization)
    code.approval_mode = "manual"
    await db.flush()
    assert await chat.say(_dashed(code)) == [copy.waiting_approval(organization.name)]
    worker = await _worker(db, organization)
    assert (worker.status, worker.pending_reason) == ("pending_approval", "manual")
    assert await _count(db, ChatContext) == 0  # no topic until approved
    assert await chat.say("halo") == [copy.waiting_approval(organization.name)]


async def test_blocked_worker_cannot_rejoin(
    chat: Chat, db: AsyncSession, organization: Workspace
) -> None:
    code = await _topic(db, organization)
    db.add(ExtensionWorker(workspace_id=organization.id, name="Budi", telegram_user_id=CHAT,
                           status="blocked"))  # fmt: skip
    await db.flush()
    assert await chat.say(_dashed(code)) == [copy.CODE_CLOSED]
    assert await _count(db, FormAssignment) == 0


async def test_same_topic_again(chat: Chat, db: AsyncSession, organization: Workspace) -> None:
    code = await _topic(db, organization)
    await chat.say(_dashed(code))
    await chat.tap("join:keep")
    (reply,) = await chat.say(_dashed(code))
    assert reply.startswith("Anda sudah tergabung di")
    await db.refresh(code)
    assert code.use_count == 1


async def _joined_two_codes(
    chat: Chat, db: AsyncSession, organization: Workspace
) -> tuple[JoinCode, JoinCode, list[str]]:
    first = await _topic(db, organization)
    other_org = Workspace(name="Dinas Peternakan Garut", type="organization")
    db.add(other_org)
    await db.flush()
    second = await _topic(db, other_org, name="Catatan Ternak")
    await chat.say(_dashed(first))
    await chat.tap("join:keep")
    replies = await chat.say(_dashed(second))
    return first, second, replies


async def test_other_topic_offers_switch_add_cancel(
    chat: Chat, db: AsyncSession, organization: Workspace
) -> None:
    _, _, (reply,) = await _joined_two_codes(chat, db, organization)
    assert "Dinas Peternakan Garut · Catatan Ternak" in reply
    assert chat.buttons() == ["join:switch", "join:add", "join:cancel"]
    assert await chat.tap("join:cancel") == [copy.CANCELLED]
    assert await chat.tap("join:add") == [copy.CHOICE_EXPIRED]  # the choice is used up
    assert await _count(db, FormAssignment) == 1


async def test_add_keeps_both_topics(chat: Chat, db: AsyncSession, organization: Workspace) -> None:
    _, second, _ = await _joined_two_codes(chat, db, organization)
    (reply,) = await chat.tap("join:add")
    assert reply.startswith("Siap, laporan berikutnya masuk ke *Dinas Peternakan Garut")
    rows = (await db.scalars(select(FormAssignment))).all()
    assert sorted(a.status for a in rows) == ["active", "active"]
    context = await db.scalar(select(ChatContext))
    new = next(a for a in rows if a.form_id == second.form_id)
    assert context is not None and context.active_assignment_id == new.id
    # The same person is now a worker in two organizations.
    assert await _count(db, ExtensionWorker) == 2


async def test_switch_leaves_the_old_topic(
    chat: Chat, db: AsyncSession, organization: Workspace
) -> None:
    first, _, _ = await _joined_two_codes(chat, db, organization)
    await chat.tap("join:switch")
    old = await db.scalar(select(FormAssignment).where(FormAssignment.form_id == first.form_id))
    assert old is not None and old.status == "left"


async def test_mid_topic_bare_letters_are_not_a_code(
    chat: Chat, db: AsyncSession, organization: Workspace
) -> None:
    code = await _topic(db, organization)
    other = await _topic(db, organization, name="Topik Lain")
    await chat.say(_dashed(code))
    await chat.tap("join:keep")
    # Outside a question the report flow reads it as a code: switch or add (3.7).
    assert await chat.say(other.code) == [copy.switch_or_add(organization.name, "Topik Lain")]
    assert await _count(db, FormAssignment) == 1


async def test_messages_belong_to_the_active_topics_organization(
    chat: Chat, db: AsyncSession, organization: Workspace
) -> None:
    await chat.say("halo")  # before joining: nobody's
    code = await _topic(db, organization)
    await chat.say(_dashed(code))
    await chat.tap("join:keep")
    conversation = await db.scalar(select(Conversation))
    assert conversation is not None

    rows = (await db.scalars(select(Message).order_by(Message.created_at, Message.id))).all()
    owners = [(m.direction, m.body, m.workspace_id, m.conversation_id) for m in rows]
    stranger, *joined = owners
    assert stranger == ("in", "halo", None, None)
    assert owners[1] == ("out", copy.JOIN_FIRST, None, None)
    for direction, _, workspace_id, conversation_id in joined[1:]:
        assert (workspace_id, conversation_id) == (organization.id, conversation.id), direction


async def test_switching_moves_new_messages_only(
    chat: Chat, db: AsyncSession, organization: Workspace
) -> None:
    _, second, _ = await _joined_two_codes(chat, db, organization)
    await chat.tap("join:switch")
    before = {m.id for m in (await db.scalars(select(Message))).all()}
    await chat.say("mulai")

    new = (await db.scalars(select(Message).where(Message.id.not_in(before)))).all()
    other_org = await db.scalar(
        select(Workspace.id).where(Workspace.name == "Dinas Peternakan Garut")
    )
    assert new and {m.workspace_id for m in new} == {other_org}
    first_org_messages = (
        await db.scalars(select(Message).where(Message.workspace_id == organization.id))
    ).all()
    assert first_org_messages  # the earlier messages stay with the first organization
    assert second.workspace_id == other_org
