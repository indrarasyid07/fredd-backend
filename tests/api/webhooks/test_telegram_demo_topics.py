"""One person on both demo structures (fixtures/demo/structures.json): joined from the QR link
(`/start CODE`), switching with `topik`, and what happens to an unfinished report."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.speech import fake_voice_note
from app.modules.auth.models import User
from app.modules.conversations.engine import copy
from app.modules.conversations.models import Conversation
from app.modules.extension_workers.models import FormAssignment
from app.modules.forms.models import Form
from app.modules.join_codes import repository as join_code_repo
from app.modules.join_codes.models import JoinCode
from app.modules.workspaces.models import Workspace
from scripts import demo_structures
from tests.api.webhooks.test_telegram_voice_lab import LabPhotoChat
from tests.telegram_fixtures import FakeTelegram

LIVESTOCK, LAB = "Laporan Kesehatan Ternak", "Uji Sampel Air (Voice Lab)"


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> LabPhotoChat:
    return LabPhotoChat(client, bot)


async def _links(db: AsyncSession, workspace: Workspace, user: User) -> dict[str, str]:
    """Each structure's QR text: what Telegram sends when the person taps Start."""
    await demo_structures.seed_structures(db, workspace.id, user.id)
    out = {}
    for form in (await db.scalars(select(Form).where(Form.workspace_id == workspace.id))).all():
        code = await join_code_repo.get_live_for_form(db, workspace.id, form.id)
        assert code is not None
        out[form.name] = f"/start {code.code}"
    return out


async def _draft(db: AsyncSession, name: str) -> dict:
    conversation = await db.scalar(
        select(Conversation).join(Form, Form.id == Conversation.form_id).where(Form.name == name)
    )
    assert conversation is not None
    await db.refresh(conversation)
    return conversation.state


async def _both_topics(chat: LabPhotoChat, links: dict[str, str], org: str) -> None:
    (welcome,) = await chat.say(links[LIVESTOCK])  # scanned the first QR, tapped Start
    assert LIVESTOCK in welcome and chat.buttons() == ["join:keep", "join:change"]
    await chat.tap("join:keep")
    (offer,) = await chat.say(links[LAB])  # scanned the second QR
    assert offer == copy.switch_or_add(org, LAB)
    await chat.tap("join:add")


async def test_qr_join_then_switch_keeps_both_drafts(
    chat: LabPhotoChat, db: AsyncSession, organization: Workspace, user: User, bot: FakeTelegram
) -> None:
    links = await _links(db, organization, user)
    await _both_topics(chat, links, organization.name)

    # A livestock report, two answers in.
    assert await chat.say("topik") == [copy.CHOOSE_TOPIC]
    await chat.tap(chat.button(f"{organization.name} · {LIVESTOCK}"))
    await chat.share_location()
    (third,) = await chat.say("Pak Slamet")
    assert "3/8" in third

    # Over to the lab: the voice prompt, one voice note, then the photo question.
    await chat.say("topik")
    (prompt,) = await chat.tap(chat.button(f"{organization.name} · {LAB}"))
    assert "ucapkan atau ketik hasilnya" in prompt.lower()
    bot.files["v1"] = fake_voice_note("sampel S-7, pH 7,1, suhu 26 derajat, volume 100")
    replies = await chat.voice("v1")
    assert "foto sampel" in replies[-1].lower()

    # Back to livestock: carries on at question 3, answers intact.
    await chat.say("topik")
    (resumed,) = await chat.tap(chat.button(f"{organization.name} · {LIVESTOCK}"))
    assert "3/8" in resumed
    assert (await _draft(db, LIVESTOCK))["answers"]["farmer_name"] == "Pak Slamet"

    # And the lab still waits for its photo, voice values kept.
    await chat.say("topik")
    (resumed,) = await chat.tap(chat.button(f"{organization.name} · {LAB}"))
    assert "foto sampel" in resumed.lower()
    assert (await _draft(db, LAB))["answers"]["suhu"] == "26"


async def test_rescanning_a_joined_qr_goes_back_and_keeps_its_draft(
    chat: LabPhotoChat, db: AsyncSession, organization: Workspace, user: User
) -> None:
    """Someone on the lab scans the livestock QR again instead of typing `topik`: no
    Pindah/Tambah question, no new join, the unfinished report carries on."""
    links = await _links(db, organization, user)
    await _both_topics(chat, links, organization.name)
    await chat.say("topik")
    await chat.tap(chat.button(f"{organization.name} · {LIVESTOCK}"))
    await chat.share_location()
    await chat.say("Pak Slamet")
    await chat.say("topik")
    await chat.tap(chat.button(f"{organization.name} · {LAB}"))
    uses = await _uses(db, organization)

    note, resumed = await chat.say(links[LIVESTOCK])
    assert note == copy.back_to_topic(organization.name, LIVESTOCK)
    assert "3/8" in resumed  # where the report was left
    assert (await _draft(db, LIVESTOCK))["answers"]["farmer_name"] == "Pak Slamet"
    assert await _uses(db, organization) == uses  # not counted as another join
    assert await db.scalar(select(func.count()).select_from(FormAssignment)) == 2

    # The next message answers the livestock question, and the lab is still one `topik` away.
    (fourth,) = await chat.tap(chat.button("Sapi"))
    assert "4/8" in fourth
    note, _ = await chat.say(links[LAB])  # the lab's QR again: back to its photo question
    assert note == copy.back_to_topic(organization.name, LAB)


async def _uses(db: AsyncSession, workspace: Workspace) -> int:
    rows = await db.scalars(select(JoinCode.use_count).where(JoinCode.workspace_id == workspace.id))
    return sum(rows.all())


async def test_pindah_leaves_the_old_structure_and_its_draft(
    chat: LabPhotoChat, db: AsyncSession, organization: Workspace, user: User
) -> None:
    """Pindah is a real leave: the old structure (and its unfinished report) is dropped."""
    links = await _links(db, organization, user)
    await chat.say(links[LIVESTOCK])
    await chat.tap("join:keep")
    await chat.say("mulai")
    await chat.share_location()
    await chat.say(links[LAB])
    await chat.tap("join:switch")

    statuses = sorted(a.status for a in (await db.scalars(select(FormAssignment))).all())
    assert statuses == ["active", "left"]
    (only,) = await chat.say("topik")
    assert only.startswith("Anda hanya tergabung di") and LAB in only


async def test_typed_bare_code_of_a_joined_topic_goes_back_too(
    chat: LabPhotoChat, db: AsyncSession, organization: Workspace, user: User
) -> None:
    """The code typed without dash or /start, outside a question, takes the same way back."""
    links = await _links(db, organization, user)
    await chat.say(links[LIVESTOCK])
    await chat.tap("join:keep")
    await chat.say("mulai")
    await chat.share_location()  # livestock draft at 2/8
    await chat.say(links[LAB])
    await chat.tap("join:add")  # now on the lab, nothing started

    note, resumed = await chat.say(links[LIVESTOCK].removeprefix("/start "))
    assert note == copy.back_to_topic(organization.name, LIVESTOCK)
    assert "2/8" in resumed
