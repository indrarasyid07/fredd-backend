import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.forms.models import Form, FormTemplate, FormTemplateSector, FormVersion


async def get_form(db: AsyncSession, workspace_id: uuid.UUID, form_id: uuid.UUID) -> Form | None:
    query = select(Form).where(Form.id == form_id, Form.workspace_id == workspace_id)
    return await db.scalar(query)


async def get_form_for_update(
    db: AsyncSession, workspace_id: uuid.UUID, form_id: uuid.UUID
) -> Form | None:
    """Locks the row so two autosaves of the same form apply one after the other."""
    query = (
        select(Form).where(Form.id == form_id, Form.workspace_id == workspace_id).with_for_update()
    )
    return await db.scalar(query)


async def list_forms(
    db: AsyncSession, workspace_id: uuid.UUID, *, before: uuid.UUID | None, limit: int
) -> list[Form]:
    """Newest first. Ids are UUID v7, so id order is creation order."""
    query = select(Form).where(Form.workspace_id == workspace_id)
    if before is not None:
        query = query.where(Form.id < before)
    return list(await db.scalars(query.order_by(Form.id.desc()).limit(limit + 1)))


async def get_form_version(
    db: AsyncSession, workspace_id: uuid.UUID, version_id: uuid.UUID
) -> FormVersion | None:
    query = select(FormVersion).where(
        FormVersion.id == version_id, FormVersion.workspace_id == workspace_id
    )
    return await db.scalar(query)


async def get_drafts(
    db: AsyncSession, form_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, FormVersion]:
    """The editable draft version of each form that has one."""
    if not form_ids:
        return {}
    query = select(FormVersion).where(
        FormVersion.form_id.in_(form_ids), FormVersion.published_at.is_(None)
    )
    return {v.form_id: v for v in await db.scalars(query)}


async def next_version_number(db: AsyncSession, form_id: uuid.UUID) -> int:
    latest = await db.scalar(
        select(func.max(FormVersion.version)).where(FormVersion.form_id == form_id)
    )
    return (latest or 0) + 1


async def get_versions(
    db: AsyncSession, version_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, FormVersion]:
    if not version_ids:
        return {}
    query = select(FormVersion).where(FormVersion.id.in_(version_ids))
    return {v.id: v for v in await db.scalars(query)}


async def list_template_sectors(db: AsyncSession) -> list[FormTemplateSector]:
    return list(await db.scalars(select(FormTemplateSector).order_by(FormTemplateSector.position)))


async def list_templates(db: AsyncSession) -> list[FormTemplate]:
    return list(await db.scalars(select(FormTemplate).order_by(FormTemplate.position)))


async def get_template_sector_by_code(db: AsyncSession, code: str) -> FormTemplateSector | None:
    return await db.scalar(select(FormTemplateSector).where(FormTemplateSector.code == code))


async def get_template_by_code(db: AsyncSession, code: str) -> FormTemplate | None:
    return await db.scalar(select(FormTemplate).where(FormTemplate.code == code))
