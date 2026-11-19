import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.forms.models import Form, FormVersion


async def get_form(db: AsyncSession, workspace_id: uuid.UUID, form_id: uuid.UUID) -> Form | None:
    query = select(Form).where(Form.id == form_id, Form.workspace_id == workspace_id)
    return await db.scalar(query)


async def get_form_version(
    db: AsyncSession, workspace_id: uuid.UUID, version_id: uuid.UUID
) -> FormVersion | None:
    query = select(FormVersion).where(
        FormVersion.id == version_id, FormVersion.workspace_id == workspace_id
    )
    return await db.scalar(query)
