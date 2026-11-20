"""Photos and files from the chat are copied to Fluctuz storage (roadmap 3.8): under the topic's
organization, checked before storing, never for a stranger, and never lost when a copy fails."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversations import media
from app.modules.conversations.engine import copy
from app.modules.conversations.models import Message
from app.modules.reports.models import ReportPhoto
from app.modules.workspaces.models import Workspace
from tests.api.webhooks.test_telegram_report_flow import Worker, _conversation, _joined
from tests.conftest import MemoryStorage
from tests.telegram_fixtures import FakeTelegram, telegram_update

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60


class PhotoChat(Worker):
    async def photo(self, file_id: str, *, size: int = 64, group: str | None = None) -> list[str]:
        update = telegram_update("photo", update_id=self._id())
        message: dict[str, Any] = update["message"]
        message["date"] += self.next_id
        message["message_id"] = self.next_id
        message.pop("caption", None)
        message["photo"] = [{"file_id": file_id, "file_unique_id": file_id, "file_size": size}]
        if group:
            message["media_group_id"] = group
        return await self._send(update)


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> PhotoChat:
    return PhotoChat(client, bot)


async def _photos(db: AsyncSession) -> list[Message]:
    rows = await db.scalars(select(Message).where(Message.kind == "photo"))
    return list(rows)


async def _to_photo_question(chat: PhotoChat) -> None:
    await chat.say("mulai")
    await chat.share_location()
    await chat.say("Pak Slamet")
    await chat.say("1,5")
    await chat.tap(chat.button("Terserang"))


async def test_photo_answer_is_stored_under_the_organization(
    chat: PhotoChat,
    db: AsyncSession,
    organization: Workspace,
    bot: FakeTelegram,
    media_store: MemoryStorage,
) -> None:
    await _joined(chat, db, organization)
    await _to_photo_question(chat)
    bot.files["photo-1"] = JPEG
    await chat.photo("photo-1")
    await chat.tap("done")
    await chat.tap("submit")

    (message,) = await _photos(db)
    assert message.media_key is not None
    assert message.media_key.startswith(f"workspaces/{organization.id}/messages/")
    assert message.media_key.endswith(f"{message.id}.jpg")
    assert media_store.objects[message.media_key] == (JPEG, "image/jpeg")
    photo = await db.scalar(select(ReportPhoto))
    assert photo is not None and photo.object_key == message.media_key


async def test_photo_before_start_begins_the_report(
    chat: PhotoChat, db: AsyncSession, organization: Workspace, bot: FakeTelegram
) -> None:
    await _joined(chat, db, organization)
    bot.files.update({"a": JPEG, "b": PNG})
    saved, question = await chat.photo("a", group="album-1")
    assert saved == copy.photo_first_saved(1) and "2/5" in question
    assert await chat.photo("b", group="album-1") == []  # the rest of the album, quietly

    conversation = await _conversation(db)
    keys = [m.media_key for m in await _photos(db)]
    assert conversation.state["answers"]["photos"] == keys
    assert keys[1] is not None and keys[1].endswith(".png")


async def test_stranger_photo_is_never_downloaded(
    chat: PhotoChat, db: AsyncSession, bot: FakeTelegram, media_store: MemoryStorage
) -> None:
    bot.files["x"] = JPEG
    await chat.photo("x")
    assert bot.downloads == [] and media_store.objects == {}
    (message,) = await _photos(db)
    assert message.media_key is None and message.workspace_id is None


async def test_large_or_fake_photo_is_refused(
    chat: PhotoChat, db: AsyncSession, organization: Workspace, bot: FakeTelegram
) -> None:
    await _joined(chat, db, organization)
    await _to_photo_question(chat)
    assert await chat.photo("big", size=25 * 1024 * 1024) == [copy.MEDIA_TOO_LARGE]
    assert bot.downloads == []  # refused from the size Telegram announced
    bot.files["fake"] = b"<html>not a photo</html>"
    assert await chat.photo("fake") == [copy.MEDIA_WRONG_TYPE]
    assert "photos" not in (await _conversation(db)).state["answers"]


async def test_failed_download_keeps_the_telegram_reference(
    chat: PhotoChat, db: AsyncSession, organization: Workspace, media_store: MemoryStorage
) -> None:
    await _joined(chat, db, organization)
    await _to_photo_question(chat)
    await chat.photo("gone")  # not in bot.files: Telegram answers an error
    assert media_store.objects == {}
    assert (await _conversation(db)).state["answers"]["photos"] == ["telegram:gone"]


@pytest.mark.parametrize(
    ("kind", "data", "found"),
    [
        ("photo", JPEG, ("image/jpeg", ".jpg")),
        ("photo", PNG, ("image/png", ".png")),
        ("photo", b"RIFF\x00\x00\x00\x00WEBPVP8 ", ("image/webp", ".webp")),
        ("photo", b"%PDF-1.7", None),
        ("document", b"%PDF-1.7", ("application/pdf", ".pdf")),
        ("video", b"\x00\x00\x00\x18ftypmp42", ("video/mp4", ".mp4")),
        ("voice", b"OggS\x00", ("audio/ogg", ".ogg")),
        ("document", b"MZ\x90\x00", None),  # an executable is never stored
    ],
)
def test_sniff_checks_the_real_bytes(kind: str, data: bytes, found: Any) -> None:
    assert media.sniff(kind, data) == found
