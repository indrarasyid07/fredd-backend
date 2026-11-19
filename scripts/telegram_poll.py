"""Run the development Telegram bot without a public URL (roadmap 3.9).

    uv run python -m scripts.telegram_poll

Reads TELEGRAM_BOT_TOKEN from .env, long-polls getUpdates and feeds every update through the
same path as the webhook (store once, queue the chat). Replies are sent by the worker, so also
run `uv run taskiq worker app.worker:broker`, or set QUEUE_INLINE=true to do it all here.

Development only. It refuses to run when the bot has a webhook: a bot has one delivery mode,
and that webhook may belong to staging or production. Use your own development bot.
"""

import asyncio
import logging
import sys

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.queue import broker
from app.core.redis import redis
from app.db import models as _models  # noqa: F401  every table, as in the worker
from app.db.session import open_session
from app.modules.channels import telegram
from app.modules.conversations import jobs, service

logger = logging.getLogger("app.telegram_poll")
OFFSET_KEY = "telegram:poll-offset"
WAIT_SECONDS = 30


async def handle(update: dict[str, object]) -> None:
    async with open_session() as db:
        received = await service.receive_telegram(db, update)
    if received.process is not None:
        channel_id, chat_id = received.process
        await jobs.process_chat_job.kiq(str(channel_id), chat_id)
    if received.leave_chat is not None:
        await jobs.leave_chat_job.kiq(received.leave_chat)


async def main() -> int:
    configure_logging()
    if not settings.is_development:
        print("Mode polling hanya untuk ENVIRONMENT=development.", file=sys.stderr)
        return 1
    if not settings.telegram_bot_token:
        print("Isi TELEGRAM_BOT_TOKEN di .env dengan token bot development Anda.", file=sys.stderr)
        return 1
    client = telegram.get_client()
    me = await client.call("getMe")
    hook = await client.call("getWebhookInfo")
    if hook.get("url"):
        print(
            f"@{me.get('username')} memakai webhook, jadi polling tidak bisa dipakai. "
            "Pastikan ini bot development Anda sendiri, lalu hapus webhook-nya "
            "(deleteWebhook) secara manual.",
            file=sys.stderr,
        )
        return 1
    await broker.startup()
    print(
        f"Polling @{me.get('username')}. Kirim pesan ke bot dari Telegram. Ctrl+C untuk berhenti."
    )
    try:
        while True:
            offset = await redis.get(OFFSET_KEY)
            try:
                updates = await client.get_updates(int(offset) if offset else None, WAIT_SECONDS)
            except telegram.TelegramError as exc:
                logger.warning("getUpdates failed: %s %s", exc.status, exc.description)
                await asyncio.sleep(5)
                continue
            for update in updates:
                try:
                    await handle(update)
                except Exception:
                    # Not acknowledged: the next getUpdates returns it again.
                    logger.exception("update %s failed; retrying", update.get("update_id"))
                    await asyncio.sleep(5)
                    break
                await redis.set(OFFSET_KEY, int(update["update_id"]) + 1)
    finally:
        await broker.shutdown()
        await client.aclose()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
