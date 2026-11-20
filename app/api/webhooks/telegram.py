import hmac
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.modules.conversations import jobs, service

logger = logging.getLogger(__name__)
router = APIRouter()

# Telegram updates are a few KB; anything far bigger is not from Telegram.
MAX_BODY_BYTES = 256 * 1024


def _status(code: int) -> Response:
    return JSONResponse({"ok": code == 200}, status_code=code)


@router.post("/telegram")
async def telegram_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> Response:
    """Store the update and answer 200 at once; a worker processes it (never inline)."""
    expected = settings.telegram_webhook_secret
    if not expected:
        return _status(404)
    if not secret or not hmac.compare_digest(secret.encode(), expected.encode()):
        return _status(401)
    if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
        return _status(413)
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return _status(413)
    try:
        update = json.loads(body)
    except ValueError:
        # Answering an error makes Telegram resend the same broken update forever.
        logger.warning("telegram webhook: body is not JSON")
        return _status(200)
    if not isinstance(update, dict):
        return _status(200)

    received = await service.receive_telegram(db, update)
    if received.process is not None:
        channel_id, chat_id = received.process
        await jobs.process_chat_job.kiq(str(channel_id), chat_id)
    for message_id in received.deliver:
        await jobs.deliver_message_job.kiq(str(message_id))
    if received.leave_chat is not None:
        await jobs.leave_chat_job.kiq(received.leave_chat)
    return _status(200)
