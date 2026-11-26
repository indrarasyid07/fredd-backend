"""The forms read interface other domains rely on (interface 2), against the real database."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.auth.models import User
from app.modules.forms import errors, service
from app.modules.forms.models import FormVersion
from app.modules.forms.schemas import FormDefinition
from app.modules.workspaces.models import Workspace
from tests.form_definitions import crop_survey


async def _version(db: AsyncSession, form_id: object) -> FormVersion:
    return (await db.scalars(select(FormVersion).where(FormVersion.form_id == form_id))).one()


async def test_create_form_stores_a_draft_version(
    db: AsyncSession, organization: Workspace, user: User
) -> None:
    definition = FormDefinition.model_validate(crop_survey())
    form = await service.create_form(db, organization.id, user.id, "Survei", definition)

    assert form.status == "draft"
    assert form.current_version_id is None
    version = await _version(db, form.id)
    assert (version.version, version.published_at) == (1, None)
    assert version.definition == definition.to_json()


async def test_draft_is_not_a_published_definition(
    db: AsyncSession, organization: Workspace, user: User
) -> None:
    definition = FormDefinition.model_validate(crop_survey())
    form = await service.create_form(db, organization.id, user.id, "Survei", definition)
    version = await _version(db, form.id)

    with pytest.raises(errors.FormVersionNotFound):
        await service.get_version_definition(db, organization.id, version.id)
    draft = await service.get_version_definition(
        db, organization.id, version.id, published_only=False
    )
    assert (draft.published, draft.definition) == (False, definition)

    version.published_at = now_utc()
    await db.flush()
    published = await service.get_version_definition(db, organization.id, version.id)
    assert (published.form_id, published.version, published.published) == (form.id, 1, True)
    assert published.definition.field_with_role("condition") is not None


async def test_other_workspace_sees_nothing(
    db: AsyncSession, organization: Workspace, user: User
) -> None:
    definition = FormDefinition.model_validate(crop_survey())
    form = await service.create_form(db, organization.id, user.id, "Survei", definition)
    version = await _version(db, form.id)
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()

    with pytest.raises(errors.FormNotFound):
        await service.get_form(db, other.id, form.id)
    with pytest.raises(errors.FormVersionNotFound):
        await service.get_version_definition(db, other.id, version.id, published_only=False)


async def test_one_draft_per_form(db: AsyncSession, organization: Workspace, user: User) -> None:
    definition = FormDefinition.model_validate(crop_survey())
    form = await service.create_form(db, organization.id, user.id, "Survei", definition)
    db.add(
        FormVersion(
            workspace_id=organization.id,
            form_id=form.id,
            version=2,
            definition=definition.to_json(),
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def _published(db: AsyncSession, organization: Workspace, user: User):  # noqa: ANN202
    definition = FormDefinition.model_validate(crop_survey())
    form = await service.create_form(db, organization.id, user.id, "Survei", definition)
    await service.publish_form(db, organization.id, user.id, form.id)
    return form


async def test_open_draft_copies_the_active_version(
    db: AsyncSession, organization: Workspace, user: User
) -> None:
    form = await _published(db, organization, user)

    detail = await service.open_draft(db, organization.id, user.id, form.id)

    assert (detail.status, detail.current_version, detail.draft_version) == ("active", 1, 2)
    assert detail.draft is not None
    active = await service.get_version_definition(db, organization.id, form.current_version_id)
    assert detail.draft.definition.model_dump() == active.definition.model_dump()
    # Opening again returns the same draft instead of a third version.
    again = await service.open_draft(db, organization.id, user.id, form.id)
    assert again.draft is not None and again.draft.version_id == detail.draft.version_id


async def test_publishing_the_reopened_draft_makes_version_two_active(
    db: AsyncSession, organization: Workspace, user: User
) -> None:
    form = await _published(db, organization, user)
    first = form.current_version_id
    await service.open_draft(db, organization.id, user.id, form.id)

    published = await service.publish_form(db, organization.id, user.id, form.id)

    assert (published.current_version, published.draft_version) == (2, None)
    assert published.current_version_id != first
    # The old version is still readable for the reports made with it.
    assert (await service.get_version_definition(db, organization.id, first)).version == 1


async def test_discard_draft(db: AsyncSession, organization: Workspace, user: User) -> None:
    form = await _published(db, organization, user)
    await service.open_draft(db, organization.id, user.id, form.id)

    detail = await service.discard_draft(db, organization.id, user.id, form.id)

    assert (detail.current_version, detail.draft_version, detail.draft) == (1, None, None)
    # The next reopen numbers on from the highest version ever used.
    assert (await service.open_draft(db, organization.id, user.id, form.id)).draft_version == 2


async def test_draft_of_a_never_published_form_cannot_be_discarded(
    db: AsyncSession, organization: Workspace, user: User
) -> None:
    definition = FormDefinition.model_validate(crop_survey())
    form = await service.create_form(db, organization.id, user.id, "Survei", definition)

    with pytest.raises(errors.DraftIsTheOnlyVersion):
        await service.discard_draft(db, organization.id, user.id, form.id)


async def test_archived_form_cannot_be_reopened(
    db: AsyncSession, organization: Workspace, user: User
) -> None:
    form = await _published(db, organization, user)
    await service.archive_form(db, organization.id, user.id, form.id)

    with pytest.raises(errors.FormArchived):
        await service.open_draft(db, organization.id, user.id, form.id)
