"""Form rules, and the read interface other domains use (interface 2 in TEAM-WORKFLOW).

Other modules call only these functions, never the repository or models: the conversation
engine reads a version's `FormDefinition` to ask fields and apply rules, reports read the
`condition` and `area` fields to fill their filter columns.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.forms import errors, repository
from app.modules.forms.models import Form, FormVersion
from app.modules.forms.schemas import FormDefinition


@dataclass(frozen=True)
class VersionDefinition:
    form_id: uuid.UUID
    version_id: uuid.UUID
    version: int
    published: bool
    definition: FormDefinition


async def get_form(db: AsyncSession, workspace_id: uuid.UUID, form_id: uuid.UUID) -> Form:
    form = await repository.get_form(db, workspace_id, form_id)
    if form is None:
        raise errors.FormNotFound()
    return form


async def get_version_definition(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    published_only: bool = True,
) -> VersionDefinition:
    """A version's definition, parsed. Drafts count as not found unless `published_only=False`
    (the wizard's test step runs the engine on the draft)."""
    version = await repository.get_form_version(db, workspace_id, version_id)
    if version is None or (published_only and version.published_at is None):
        raise errors.FormVersionNotFound()
    return _to_version_definition(version)


async def create_form(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    name: str,
    definition: FormDefinition,
    description: str | None = None,
) -> Form:
    """A new form in `draft` with version 1 as its editable draft."""
    form = Form(
        workspace_id=workspace_id,
        name=name,
        description=description,
        status="draft",
        created_by_user_id=user_id,
    )
    db.add(form)
    await db.flush()
    db.add(
        FormVersion(
            workspace_id=workspace_id,
            form_id=form.id,
            version=1,
            definition=definition.to_json(),
        )
    )
    await db.commit()
    return form


def _to_version_definition(version: FormVersion) -> VersionDefinition:
    return VersionDefinition(
        form_id=version.form_id,
        version_id=version.id,
        version=version.version,
        published=version.published_at is not None,
        definition=FormDefinition.model_validate(version.definition),
    )
