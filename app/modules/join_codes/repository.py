import uuid

from sqlalchemy import select
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
