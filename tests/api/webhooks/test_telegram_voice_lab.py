"""Voice Lab on the Telegram webhook (roadmap 12.3): in a voice-mode topic a voice note is stored,
transcribed, fills several fields at once, and the report keeps what was heard."""

import json
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.ai import answers, speech
from app.modules.ai.speech import fake_voice_note
from app.modules.conversations.engine import copy
from app.modules.forms import service as forms
from app.modules.forms.models import Form, FormVersion
from app.modules.forms.schemas import FormDefinition
from app.modules.join_codes import repository as join_code_repo
from app.modules.join_codes.models import JoinCode
from app.modules.reports.models import Report, ReportPhoto
from app.modules.workspaces.models import Workspace
from scripts import demo_structures
from tests.api.webhooks.test_telegram_join import _dashed
from tests.api.webhooks.test_telegram_media import JPEG, PhotoChat
from tests.api.webhooks.test_telegram_report_flow import Worker
from tests.conftest import MemoryStorage
from tests.telegram_fixtures import FakeTelegram, telegram_update

LAB = {
    "fields": [
        {"key": "sample", "type": "short_text", "label": "Nomor sampel",
         "question": "Nomor sampel?", "voice_cues": ["sampel"]},
        {"key": "ph", "type": "number", "label": "pH", "question": "Berapa pH?"},
        {"key": "temp", "type": "number", "label": "Suhu", "question": "Berapa suhu?",
         "unit": "°C", "unit_aliases": ["derajat"]},
    ],
    "rules": [],
}  # fmt: skip


class LabChat(Worker):
    async def voice(self, file_id: str) -> list[str]:
        update = telegram_update("voice", update_id=self._id())
        message: dict[str, Any] = update["message"]
        message["date"] += self.next_id
        message["message_id"] = self.next_id
        message["voice"] = {"file_id": file_id, "duration": 4, "mime_type": "audio/ogg"}
        return await self._send(update)


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> LabChat:
    return LabChat(client, bot)


async def _lab_topic(
    db: AsyncSession, workspace: Workspace, mode: str = "voice", definition: Any = LAB
) -> JoinCode:
    form = await forms.create_form(
        db, workspace.id, None, "Uji Sampel Air", FormDefinition.model_validate(definition)
    )
    row = await db.get(Form, form.id)
    version = await db.scalar(select(FormVersion).where(FormVersion.form_id == form.id))
    assert row is not None and version is not None
    row.status, row.settings = "active", {**row.settings, "input_mode": mode}
    version.published_at = now_utc()
    row.current_version_id = version.id
    code = await join_code_repo.get_live_for_form(db, workspace.id, form.id)
    assert code is not None
    await db.flush()
    return code


async def _join(chat: LabChat, db: AsyncSession, workspace: Workspace, mode: str = "voice") -> None:
    code = await _lab_topic(db, workspace, mode)
    await chat.say(_dashed(code))
    (ready,) = await chat.tap("join:keep")
    assert ready == (copy.AFTER_KEEP_VOICE if mode == "voice" else copy.AFTER_KEEP)


async def test_voice_note_fills_the_report(
    chat: LabChat,
    db: AsyncSession,
    organization: Workspace,
    bot: FakeTelegram,
    media_store: MemoryStorage,
) -> None:
    await _join(chat, db, organization)
    bot.files["v1"] = fake_voice_note("sampel S-2041, pH 6,8, suhu 25 derajat")
    replies = await chat.voice("v1")
    assert replies[0].startswith("Tercatat: Nomor sampel *S-2041*")
    assert "Suhu *25 °C*" in replies[0]
    assert replies[-1].startswith("Ringkasan laporan")  # nothing left to ask
    await chat.tap("submit")

    report = await db.scalar(select(Report))
    assert report is not None
    assert report.answers == {"sample": "S-2041", "ph": "6.8", "temp": "25"}
    assert report.voice is not None
    assert report.voice["transcript"] == "sampel S-2041, pH 6,8, suhu 25 derajat"
    assert report.voice["audio"] in media_store.objects  # the recording is kept
    assert report.voice["heard"]["temp"] == "25 derajat"


async def test_doubtful_value_is_asked_again(
    chat: LabChat, db: AsyncSession, organization: Workspace, bot: FakeTelegram
) -> None:
    await _join(chat, db, organization)
    bot.files["v1"] = fake_voice_note("sampel S-1, pH 7, suhu 25 ml")
    heard, question = await chat.voice("v1")
    assert 'Perlu dipastikan: Suhu ("25 ml")' in heard
    assert "Berapa suhu?" in question
    bot.files["v2"] = fake_voice_note("26 derajat")
    await chat.voice("v2")  # a spoken answer to the single question
    await chat.tap("submit")
    report = await db.scalar(select(Report))
    assert report is not None and report.answers["temp"] == "26"


async def test_failing_speech_provider_asks_to_resend(
    chat: LabChat,
    db: AsyncSession,
    organization: Workspace,
    bot: FakeTelegram,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Broken:
        name = "broken"

        async def transcribe(self, audio: bytes, content_type: str, language: str = "id") -> Any:
            raise RuntimeError("provider down")

    await _join(chat, db, organization)
    monkeypatch.setattr(speech, "override", Broken())
    bot.files["v1"] = fake_voice_note("pH 7")
    assert await chat.voice("v1") == [copy.VOICE_UNREAD]


async def test_chat_mode_topic_is_not_transcribed(
    chat: LabChat, db: AsyncSession, organization: Workspace, bot: FakeTelegram
) -> None:
    await _join(chat, db, organization, mode="chat")
    first = (await chat.say("mulai"))[-1]
    assert "Nomor sampel?" in first  # one question at a time, as before
    bot.files["v1"] = fake_voice_note("S-1")
    replies = await chat.voice("v1")
    assert not any(r.startswith("Tercatat") for r in replies)


class LabPhotoChat(LabChat, PhotoChat):
    pass


async def test_demo_voice_lab_asks_for_the_sample_photo_after_the_voice_note(
    client: AsyncClient,
    db: AsyncSession,
    organization: Workspace,
    bot: FakeTelegram,
    media_store: MemoryStorage,
) -> None:
    """The demo's Voice Lab (fixtures/demo/structures.json): one voice note fills the values,
    then the bot asks for the photo, and the report keeps both."""
    fixture = json.loads((demo_structures.FIXTURES / "demo" / "structures.json").read_text())
    lab = next(s for s in fixture["structures"] if s["settings"]["input_mode"] == "voice")
    chat = LabPhotoChat(client, bot)
    code = await _lab_topic(db, organization, definition=lab["definition"])
    await chat.say(_dashed(code))
    await chat.tap("join:keep")

    bot.files["v1"] = fake_voice_note("sampel S-2041, pH 6,8, suhu 25 derajat, volume 250")
    replies = await chat.voice("v1")
    assert replies[0].startswith("Tercatat: Nomor sampel *S-2041*")
    assert "foto sampel" in replies[-1].lower()  # the one thing a voice note cannot carry
    bot.files["p1"] = JPEG
    await chat.photo("p1")
    await chat.tap("done")
    await chat.tap("submit")

    report = await db.scalar(select(Report))
    assert report is not None and report.voice is not None
    assert report.answers["suhu"] == "25" and len(report.answers["foto_sampel"]) == 1
    photo = await db.scalar(select(ReportPhoto))
    assert photo is not None and photo.object_key in media_store.objects


class FakeSentenceReader:
    name = "fake"

    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.asked: list[tuple[str, ...]] = []

    async def read_sentence(
        self, definition: FormDefinition, keys: Any, said: str, *, today: Any
    ) -> dict[str, str]:
        self.asked.append(tuple(keys))
        return {k: v for k, v in self.values.items() if k in keys}


async def test_loose_voice_note_is_read_by_the_model_and_confirmed(
    client: AsyncClient,
    db: AsyncSession,
    organization: Workspace,
    bot: FakeTelegram,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "pH-nya kira-kira enam koma delapan, suhunya dua puluh lima": the rules miss both, a
    language model reads them, the worker confirms each, and the report keeps what it read."""
    fixture = json.loads((demo_structures.FIXTURES / "demo" / "structures.json").read_text())
    lab = next(s for s in fixture["structures"] if s["settings"]["input_mode"] == "voice")
    model = FakeSentenceReader({"ph": "6,8", "suhu": "25"})
    monkeypatch.setattr(answers, "sentence_override", model)
    chat = LabPhotoChat(client, bot)
    code = await _lab_topic(db, organization, definition=lab["definition"])
    await chat.say(_dashed(code))
    await chat.tap("join:keep")

    said = "sampel S-7, pH-nya kira-kira enam koma delapan, suhunya dua puluh lima"
    bot.files["v1"] = fake_voice_note(said)
    heard, confirm = await chat.voice("v1")
    assert model.asked == [("ph", "suhu", "volume")]
    assert "Sepertinya juga: pH *6,8* · Suhu *25 °C*" in heard
    assert confirm == copy.confirm_value("6,8")
    assert await chat.tap("yes") == [copy.confirm_value("25 °C")]
    (volume,) = await chat.tap("yes")
    assert "Berapa volume?" in volume
    (photo,) = await chat.tap("skip")
    assert "foto sampel" in photo.lower()
    bot.files["p1"] = JPEG
    await chat.photo("p1")
    await chat.tap("done")
    await chat.tap("submit")

    report = await db.scalar(select(Report))
    assert report is not None and report.voice is not None
    assert report.answers["ph"] == "6.8" and report.answers["suhu"] == "25"
    assert report.voice["ai_read"] == {"ph": "6,8", "suhu": "25"}


async def test_clear_voice_note_never_calls_the_model(
    chat: LabChat,
    db: AsyncSession,
    organization: Workspace,
    bot: FakeTelegram,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakeSentenceReader({})
    monkeypatch.setattr(answers, "sentence_override", model)
    await _join(chat, db, organization)
    bot.files["v1"] = fake_voice_note("sampel S-2041, pH 6,8, suhu 25 derajat")
    await chat.voice("v1")
    assert model.asked == []
