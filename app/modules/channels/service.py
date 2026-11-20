from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.channels import repository
from app.modules.channels.models import Channel
from app.modules.channels.schemas import BotOut


async def telegram_channel(db: AsyncSession) -> Channel:
    """The platform's Telegram bot row, created on first use (no seed step to forget)."""
    channel = await repository.get_platform_channel(db, "telegram")
    if channel is None:
        await repository.create_platform_channel(
            db, "telegram", "Fluctuz", settings.telegram_bot_username
        )
        channel = await repository.get_platform_channel(db, "telegram")
        assert channel is not None
    return channel


def _phone(digits: str) -> str:
    """6281100000000 → +62 811-0000-0000 (display only)."""
    if digits.startswith("62") and len(digits) >= 10:
        rest = digits[2:]
        return f"+62 {rest[:3]}-{rest[3:7]}-{rest[7:]}"
    return f"+{digits}"


def list_bots() -> list[BotOut]:
    """The shared bots. Same for every organization; credentials stay in the environment."""
    tg, wa = settings.telegram_bot_username, settings.whatsapp_public_number
    return [
        BotOut(
            type="whatsapp", name="WhatsApp Fluctuz", handle=_phone(wa) if wa else None,
            url=f"https://wa.me/{wa}" if wa else None, available=bool(wa),
        ),
        BotOut(
            type="telegram", name="Telegram Fluctuz", handle=f"@{tg}" if tg else None,
            url=f"https://t.me/{tg}" if tg else None, available=bool(tg),
        ),
    ]  # fmt: skip
