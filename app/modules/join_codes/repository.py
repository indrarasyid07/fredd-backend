import uuid
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.join_codes.models import JoinCode


async def get_live_for_form(
    db: AsyncSession, workspace_id: uuid.UUID, form_id: uuid.UUID, *, for_update: bool = False
) -> JoinCode | None:
    """The structure's code that is not revoked (at most one)."""
    query = select(JoinCode).where(
        JoinCode.workspace_id == workspace_id,
        JoinCode.form_id == form_id,
        JoinCode.status != "revoked",
    )
    if for_update:
        query = query.with_for_update()
    return await db.scalar(query)


async def code_exists(db: AsyncSession, code: str) -> bool:
    return await db.scalar(select(JoinCode.id).where(JoinCode.code == code)) is not None


async def get_by_code(db: AsyncSession, code: str) -> JoinCode | None:
    """Platform-wide lookup: the code itself says which organization it belongs to."""
    return await db.scalar(select(JoinCode).where(JoinCode.code == code))


async def take_use(db: AsyncSession, join_code_id: uuid.UUID, now: datetime) -> bool:
    """Count one join, atomically: False when the code filled up, closed or expired meanwhile."""
    result = await db.execute(
        update(JoinCode)
        .where(
            JoinCode.id == join_code_id,
            JoinCode.status == "active",
            or_(JoinCode.expires_at.is_(None), JoinCode.expires_at > now),
            or_(JoinCode.max_uses.is_(None), JoinCode.use_count < JoinCode.max_uses),
        )
        .values(use_count=JoinCode.use_count + 1)
        .returning(JoinCode.id)
    )
    return result.scalar_one_or_none() is not None
