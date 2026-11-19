from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.channels.models import Channel


async def get_platform_channel(db: AsyncSession, type_: str) -> Channel | None:
    return await db.scalar(
        select(Channel).where(Channel.type == type_, Channel.workspace_id.is_(None))
    )


async def create_platform_channel(
    db: AsyncSession, type_: str, display_name: str, bot_username: str | None
) -> None:
    """Concurrent first webhooks race here; the unique index keeps one row."""
    await db.execute(
        insert(Channel)
        .values(type=type_, display_name=display_name, bot_username=bot_username or None)
        .on_conflict_do_nothing(index_elements=["type"], index_where=Channel.workspace_id.is_(None))
    )
