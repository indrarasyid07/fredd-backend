import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from app.modules.channels.telegram import TelegramError
from app.modules.conversations.engine.types import Outbound

_DIR = Path(__file__).parent / "fixtures" / "webhooks" / "telegram"


def telegram_update(name: str, **changes: Any) -> dict[str, Any]:
    """A fixture update; `update_id=` and top-level changes override it."""
    data = json.loads((_DIR / f"{name}.json").read_text())
    data.update(changes)
    return data


SECRET = "s3cret-webhook-token"
URL = "/webhooks/telegram"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}


@dataclass
class FakeTelegram:
    sent: list[tuple[str, Outbound]] = field(default_factory=list)
    answered: list[str] = field(default_factory=list)
    left: list[str] = field(default_factory=list)
    fail_with: TelegramError | None = None
    # file_id → bytes "downloaded" for it; a missing id fails like Telegram would.
    files: dict[str, bytes] = field(default_factory=dict)
    downloads: list[str] = field(default_factory=list)

    async def send(self, chat_id: str, out: Outbound) -> str:
        if self.fail_with:
            raise self.fail_with
        self.sent.append((chat_id, out))
        return str(100 + len(self.sent))

    async def answer_callback(self, callback_id: str) -> None:
        self.answered.append(callback_id)

    async def leave_chat(self, chat_id: str) -> None:
        self.left.append(chat_id)

    async def download_file(self, file_id: str, max_bytes: int) -> bytes:
        self.downloads.append(file_id)
        if file_id not in self.files:
            raise TelegramError(400, "file not found")
        data = self.files[file_id]
        if len(data) > max_bytes:
            raise TelegramError(413, "file too large")
        return data


async def post_update(
    client: AsyncClient, update: dict[str, Any], headers: dict[str, str] = HEADERS
) -> int:
    return (await client.post(URL, json=update, headers=headers)).status_code
