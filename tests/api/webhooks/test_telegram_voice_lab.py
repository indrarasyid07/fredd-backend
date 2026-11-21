"""Voice Lab on the Telegram webhook (roadmap 12.3): in a voice-mode topic a voice note is stored,
transcribed, fills several fields at once, and the report keeps what was heard."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.ai import speech
from app.modules.ai.speech import fake_voice_note
from app.modules.conversations.engine import copy
from app.modules.forms import service as forms
from app.modules.forms.models import Form, FormVersion
from app.modules.forms.schemas import FormDefinition
from app.modules.join_codes import repository as join_code_repo
from app.modules.join_codes.models import JoinCode
from app.modules.reports.models import Report
from app.modules.workspaces.models import Workspace
from tests.api.webhooks.test_telegram_join import _dashed
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


async def _lab_topic(db: AsyncSession, workspace: Workspace, mode: str = "voice") -> JoinCode:
    form = await forms.create_form(
        db, workspace.id, None, "Uji Sampel Air", FormDefinition.model_validate(LAB)
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
