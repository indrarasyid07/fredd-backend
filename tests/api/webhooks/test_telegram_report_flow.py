"""The report flow on the Telegram webhook (roadmap 3.7): a confirmed worker answers every field
and the report is stored; failures, help, the 3.0 commands, topics and form versions."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.audit.models import AuditLog
from app.modules.conversations.engine import copy
from app.modules.conversations.models import Conversation
from app.modules.extension_workers.models import ChatContext, FormAssignment
from app.modules.forms.models import Form, FormVersion
from app.modules.join_codes.models import JoinCode
from app.modules.reports.models import Report, ReportPhoto
from app.modules.workspaces.models import Workspace
from tests.api.webhooks.test_telegram_join import Chat, _dashed, _topic
from tests.form_definitions import crop_survey
from tests.telegram_fixtures import FakeTelegram, telegram_update


class Worker(Chat):
    """Budi's chat, able to share a location and send a photo too."""

    async def share_location(self, lat: float = -7.2167, lng: float = 107.9) -> list[str]:
        update = telegram_update("location", update_id=self._id())
        update["message"]["location"] = {
            "latitude": lat,
            "longitude": lng,
            "horizontal_accuracy": 8,
        }
        update["message"]["date"] += self.next_id
        return await self._send(update)

    async def send_photo(self) -> list[str]:
        update = telegram_update("photo", update_id=self._id())
        update["message"]["date"] += self.next_id
        update["message"].pop("caption", None)
        return await self._send(update)

    def button(self, label_start: str) -> str:
        """The value of the last message's button whose label starts with `label_start`."""
        for b in self.bot.sent[-1][1].buttons:
            if b.label.startswith(label_start):
                return b.value
        raise AssertionError(f"no button {label_start!r} in {self.bot.sent[-1][1].buttons}")


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> Worker:
    return Worker(client, bot)


async def _joined(
    chat: Worker, db: AsyncSession, workspace: Workspace, name: str = "Survei Tanaman"
) -> JoinCode:
    code = await _topic(db, workspace, name)
    await chat.say(_dashed(code))
    await chat.tap("join:keep")
    return code


async def _conversation(db: AsyncSession) -> Conversation:
    conversation = await db.scalar(select(Conversation).order_by(Conversation.updated_at.desc()))
    assert conversation is not None
    await db.refresh(conversation)
    return conversation


async def _count(db: AsyncSession, model: Any) -> int:
    return await db.scalar(select(func.count()).select_from(model)) or 0


async def _answer_everything(chat: Worker) -> list[str]:
    """mulai → lokasi → nama petani → luas → kondisi → foto → ringkasan."""
    (first,) = await chat.say("mulai")
    assert "Survei Tanaman" in first and "1/5" in first
    (q2,) = await chat.share_location()
    assert "2/5" in q2
    (q3,) = await chat.say("Pak Slamet")
    assert "3/5" in q3
    (q4,) = await chat.say("1,5")
    assert "4/5" in q4
    await chat.tap(chat.button("Terserang"))
    await chat.send_photo()
    return await chat.tap("done")


async def test_full_report_is_stored_with_its_code(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    await _joined(chat, db, organization)
    summary = await _answer_everything(chat)
    assert "Pak Slamet" in summary[-1]
    assert [b.value for b in chat.bot.sent[-1][1].buttons] == ["submit", "edit"]

    (saved,) = await chat.tap("submit")
    report = await db.scalar(select(Report))
    assert report is not None
    assert report.code in saved and report.code.startswith("LP-")
    assert (report.condition, str(report.area_ha)) == ("infected", "1.5000")
    assert (report.latitude, report.longitude) == (-7.2167, 107.9)
    assert report.answers["farmer_name"] == "Pak Slamet"
    assert await _count(db, ReportPhoto) == 1
    conversation = await _conversation(db)
    assert conversation.status == "submitted"
    assert report.conversation_id == conversation.id
    assert report.form_version_id == conversation.form_version_id

    # The old summary's button does not make a second report.
    await chat.tap("submit")
    assert await _count(db, Report) == 1


async def test_three_failures_offer_help(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    await _joined(chat, db, organization)
    await chat.say("mulai")
    await chat.share_location()
    await chat.say("Pak Slamet")
    for _ in range(2):
        # The reason with an example, then the question again.
        reason, question = await chat.say("banyak")
        assert reason == copy.NOT_A_NUMBER and "3/5" in question
    replies = await chat.say("luas sekali")
    assert any(r.startswith(copy.THREE_FAILS) for r in replies)
    assert "help" in chat.buttons()
    assert await chat.tap("help") == [copy.HELP_SENT]
    assert (await _conversation(db)).status == "needs_help"
    assert await chat.say("halo?") == []  # waiting for an admin
    action = select(func.count()).where(AuditLog.action == "conversation.needs_help")
    assert await db.scalar(action) == 1


async def test_binding_must_be_confirmed_first(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    code = await _topic(db, organization)
    await chat.say(_dashed(code))  # no "Ya, tetap" yet
    assert await chat.say("mulai") == [copy.CONFIRM_TOPIC_FIRST]
    assert chat.buttons() == ["join:keep", "join:change"]
    assert await _count(db, Report) == 0


async def test_commands_cancel_restart_and_resume(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    await _joined(chat, db, organization)
    await chat.say("mulai")
    await chat.share_location()

    assert await chat.say("mulai") == [copy.DRAFT_EXISTS]
    (again,) = await chat.tap("resume")
    assert "2/5" in again

    assert await chat.say("batal") == [copy.CANCEL_CONFIRM]
    replies = await chat.tap("cancel:no")
    assert replies[0] == copy.KEEP_GOING and "2/5" in replies[1]
    await chat.say("batal")
    assert await chat.tap("cancel:yes") == [copy.DRAFT_CANCELLED]
    assert (await _conversation(db)).status == "idle"
    assert await chat.say("batal") == [copy.NO_DRAFT]

    await chat.say("mulai")
    await chat.share_location()
    assert await chat.say("mulai ulang") == [copy.RESTART_CONFIRM]
    (restarted,) = await chat.tap("restart:yes")
    assert "1/5" in restarted

    (listing,) = await chat.say("bantuan")
    assert listing == copy.HELP_TEXT and chat.buttons() == ["help"]


async def test_stop_releases_every_topic(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    await _joined(chat, db, organization)
    await chat.say("mulai")
    assert await chat.say("berhenti") == [copy.STOP_CONFIRM]
    assert await chat.tap("stop:no") == [copy.STOP_CANCELLED]
    await chat.say("berhenti")
    assert await chat.tap("stop:yes") == [copy.STOPPED]
    assert await db.scalar(select(FormAssignment.status)) == "left"
    assert await db.scalar(select(ChatContext.active_assignment_id)) is None
    assert await chat.say("mulai") == [copy.JOIN_FIRST]
    opted_out = select(func.count()).where(AuditLog.action == "extension_worker.opted_out")
    assert await db.scalar(opted_out) == 1


async def test_topik_switches_and_keeps_each_draft(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    await _joined(chat, db, organization)
    await chat.say("mulai")
    await chat.share_location()  # draft on Survei Tanaman, at 2/5
    other = await _topic(db, organization, "Pantau Hama")
    await chat.say(_dashed(other))
    await chat.tap("join:add")  # now on Pantau Hama

    assert await chat.say("topik") == [copy.CHOOSE_TOPIC]
    back = chat.button(f"{organization.name} · Survei Tanaman")
    (resumed,) = await chat.tap(back)
    assert "2/5" in resumed  # the draft carried on


async def test_draft_keeps_its_version_after_a_new_publish(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    await _joined(chat, db, organization)
    await chat.say("mulai")
    first = (await _conversation(db)).form_version_id
    # A new version goes live while the draft is open.
    form = await db.scalar(select(Form))
    assert form is not None
    newer = FormVersion(
        workspace_id=organization.id,
        form_id=form.id,
        version=2,
        definition=crop_survey(),
        published_at=now_utc(),
    )
    db.add(newer)
    await db.flush()
    form.current_version_id = newer.id
    await db.flush()

    await chat.share_location()
    await chat.say("Pak Slamet")
    await chat.say("2")
    await chat.tap(chat.button("Sehat"))
    await chat.tap("skip")
    await chat.tap("submit")
    report = await db.scalar(select(Report))
    assert report is not None and report.form_version_id == first != newer.id

    # The next report takes the new version.
    await chat.say("mulai")
    assert (await _conversation(db)).form_version_id == newer.id


async def test_closed_topic_takes_no_report(
    chat: Worker, db: AsyncSession, organization: Workspace
) -> None:
    await _joined(chat, db, organization)
    form = await db.scalar(select(Form))
    assert form is not None
    form.status = "archived"
    await db.flush()
    (reply,) = await chat.say("mulai")
    assert reply == copy.topic_closed(organization.name, "Survei Tanaman")
