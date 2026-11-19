from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.channels import repository
from app.modules.channels.models import Channel


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
