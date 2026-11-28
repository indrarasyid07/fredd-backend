"""Baca struk dan foto on the Telegram webhook: the receipt photo is stored, read by a language
model for the other answers, each confirmed, and the report keeps the confirmed values."""

import json
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai import answers
from app.modules.conversations.engine import copy
from app.modules.forms.schemas import FormDefinition
from app.modules.reports.models import Report
from app.modules.workspaces.models import Workspace
from scripts import demo_structures
from tests.api.webhooks.test_telegram_join import _dashed
from tests.api.webhooks.test_telegram_media import JPEG, PhotoChat
from tests.api.webhooks.test_telegram_voice_lab import _lab_topic
from tests.conftest import MemoryStorage
from tests.telegram_fixtures import FakeTelegram

FIXTURE = json.loads((demo_structures.FIXTURES / "demo" / "structures.json").read_text())
SALES = next(s for s in FIXTURE["structures"] if s["name"] == "Catatan Penjualan Hasil Panen")


class FakePhotoReader:
    name = "fake"

    def __init__(self, values: dict[str, str] | None) -> None:
        self.values = values
        self.read: list[tuple[bytes, tuple[str, ...], str]] = []

    async def read_photo(
        self,
        definition: FormDefinition,
        keys: Any,
        image: bytes,
        content_type: str,
        *,
        context: str,
        today: Any,
    ) -> dict[str, str] | None:
        self.read.append((image, tuple(keys), context))
        return None if self.values is None else dict(self.values)


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> PhotoChat:
    return PhotoChat(client, bot)


async def _sales_topic(chat: PhotoChat, db: AsyncSession, organization: Workspace) -> None:
    code = await _lab_topic(db, organization, mode="chat", definition=SALES["definition"])
    await chat.say(_dashed(code))
    await chat.tap("join:keep")
    (first,) = await chat.say("mulai")
    assert "foto nota" in first.lower()


async def test_receipt_photo_fills_the_report_after_confirmation(
    chat: PhotoChat,
    db: AsyncSession,
    organization: Workspace,
    bot: FakeTelegram,
    media_store: MemoryStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakePhotoReader({"sale_date": "2026-11-27", "buyer": "UD Tani Makmur",
                             "weight": "125,5", "total": "1250000"})  # fmt: skip
    monkeypatch.setattr(answers, "photo_override", model)
    await _sales_topic(chat, db, organization)

    bot.files["nota"] = JPEG
    note, received = await chat.photo("nota")
    ((image, keys, context),) = model.read
    assert image == JPEG  # read from storage, the same bytes Telegram sent
    assert keys[:3] == ("sale_date", "buyer", "commodity")
    assert "Photo question: Kirim foto nota" in context
    assert note.startswith("Dari foto, sepertinya: Tanggal jual *27/11/2026*")
    assert "Kirim lagi" in received

    assert await chat.tap("done") == [copy.confirm_value("27/11/2026")]
    assert await chat.tap("yes") == [copy.confirm_value("UD Tani Makmur")]
    (commodity,) = await chat.tap("yes")
    assert "Komoditas apa" in commodity  # not on the receipt: asked as usual
    (weight,) = await chat.tap(chat.button("Padi"))
    assert weight == copy.confirm_value("125,5 kg")
    (price,) = await chat.tap("yes")
    assert "harga per kilogram" in price  # not read either
    assert await chat.tap("skip") == [copy.confirm_value("1250000 Rp")]


async def test_failed_reading_asks_as_usual(
    chat: PhotoChat,
    db: AsyncSession,
    organization: Workspace,
    bot: FakeTelegram,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(answers, "photo_override", FakePhotoReader(None))
    await _sales_topic(chat, db, organization)
    bot.files["nota"] = JPEG
    (received,) = await chat.photo("nota")  # no note: as if the model were off
    assert "Kirim lagi" in received
    (question,) = await chat.tap("done")
    assert "Tanggal berapa" in question


async def test_switched_off_in_pengaturan_agent(
    chat: PhotoChat,
    db: AsyncSession,
    organization: Workspace,
    bot: FakeTelegram,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakePhotoReader({"buyer": "UD Tani Makmur"})
    monkeypatch.setattr(answers, "photo_override", model)
    organization.settings = {**organization.settings, "agent": {"voice_and_photos": False}}
    await db.flush()
    await _sales_topic(chat, db, organization)
    bot.files["nota"] = JPEG
    await chat.photo("nota")
    assert model.read == []


async def test_report_keeps_the_confirmed_values(
    chat: PhotoChat,
    db: AsyncSession,
    organization: Workspace,
    bot: FakeTelegram,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {"sale_date": "2026-11-27", "buyer": "UD Tani Makmur", "commodity": "Padi",
              "weight": "125,5", "price_per_kg": "10000", "total": "1255000"}  # fmt: skip
    monkeypatch.setattr(answers, "photo_override", FakePhotoReader(values))
    await _sales_topic(chat, db, organization)
    bot.files["nota"] = JPEG
    await chat.photo("nota")
    await chat.tap("done")
    for _ in values:
        await chat.tap("yes")
    await chat.tap("skip")  # notes
    await chat.tap("submit")
    report = await db.scalar(select(Report))
    assert report is not None
    assert report.answers["total"] == "1255000" and report.answers["commodity"] == "rice"
    assert report.answers["sale_date"] == "2026-11-27"
