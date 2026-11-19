"""Form rules, and the read interface other domains use (interface 2 in TEAM-WORKFLOW).

Other modules call only `get_version_definition`, `get_form` and `create_form`, never the
repository or models: the conversation engine reads a version's `FormDefinition` to ask fields
and apply rules, reports read the `condition` and `area` fields to fill their filter columns.
The rest serves the /forms and /form-templates endpoints (the wizard).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import InvalidCursor
from app.core.time import now_utc
from app.modules.audit import service as audit
from app.modules.forms import errors, repository
from app.modules.forms.models import Form, FormTemplate, FormTemplateSector, FormVersion
from app.modules.forms.schemas import (
    CreateFormRequest,
    DraftFormDefinition,
    FormCheckOut,
    FormDefinition,
    FormDetailOut,
    FormDraftOut,
    FormOut,
    FormProblem,
    FormSettings,
    FormTemplateOut,
    FormTemplateSectorOut,
    TemplateChipOut,
    UpdateFormRequest,
    find_problems,
)
from app.modules.join_codes import service as join_codes
from app.modules.reference_data import service as reference_data


@dataclass(frozen=True)
class VersionDefinition:
    form_id: uuid.UUID
    version_id: uuid.UUID
    version: int
    published: bool
    definition: FormDefinition


# --- Interface for other domains --------------------------------------------------------------


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
    return VersionDefinition(
        form_id=version.form_id,
        version_id=version.id,
        version=version.version,
        published=version.published_at is not None,
        definition=FormDefinition.model_validate(version.definition),
    )


async def create_form(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    name: str,
    definition: FormDefinition | DraftFormDefinition,
    description: str | None = None,
    settings: FormSettings | None = None,
) -> Form:
    """A new form in `draft` with version 1 as its editable draft."""
    form = Form(
        workspace_id=workspace_id,
        name=name,
        description=description,
        status="draft",
        created_by_user_id=user_id,
        settings=(settings or FormSettings()).model_dump(mode="json"),
    )
    db.add(form)
    await db.flush()
    # Every structure gets its join code right away (B-048); it works once the form is open.
    await join_codes.create_for_form(db, workspace_id, form.id, user_id)
    db.add(
        FormVersion(
            workspace_id=workspace_id,
            form_id=form.id,
            version=1,
            definition=_definition_json(definition),
        )
    )
    await db.commit()
    return form


# --- Wizard (/forms) ---------------------------------------------------------------------------


async def list_forms(
    db: AsyncSession, workspace_id: uuid.UUID, *, before: list[str] | None, limit: int
) -> tuple[list[FormOut], uuid.UUID | None]:
    """A page of the workspace's forms, newest first, and the last id when more follow."""
    forms = await repository.list_forms(db, workspace_id, before=_parse_id(before), limit=limit)
    more = None
    if len(forms) > limit:
        forms = forms[:limit]
        more = forms[-1].id
    drafts = await repository.get_drafts(db, [f.id for f in forms])
    current = await repository.get_versions(
        db, [f.current_version_id for f in forms if f.current_version_id]
    )
    items = [
        _form_out(
            f,
            drafts.get(f.id),
            current.get(f.current_version_id) if f.current_version_id else None,
        )
        for f in forms
    ]
    return items, more


async def create_wizard_form(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, body: CreateFormRequest
) -> FormDetailOut:
    await _check_settings(db, body.settings)
    form = await create_form(
        db,
        workspace_id,
        user_id,
        body.name,
        body.definition,
        description=body.description,
        settings=body.settings,
    )
    return await get_form_detail(db, workspace_id, form.id)


async def get_form_detail(
    db: AsyncSession, workspace_id: uuid.UUID, form_id: uuid.UUID
) -> FormDetailOut:
    form = await get_form(db, workspace_id, form_id)
    return await _detail(db, form)


async def update_form(
    db: AsyncSession, workspace_id: uuid.UUID, form_id: uuid.UUID, body: UpdateFormRequest
) -> FormDetailOut:
    """Autosave of the wizard. Only a form with a draft version can change."""
    form = await repository.get_form_for_update(db, workspace_id, form_id)
    if form is None:
        raise errors.FormNotFound()
    if form.status == "archived":
        raise errors.FormArchived()
    draft = (await repository.get_drafts(db, [form.id])).get(form.id)
    if draft is None:
        raise errors.FormNotEditable()
    if body.name is not None:
        form.name = body.name
    if "description" in body.model_fields_set:
        form.description = body.description
    if body.settings is not None:
        await _check_settings(db, body.settings)
        form.settings = body.settings.model_dump(mode="json")
    if body.definition is not None:
        draft.definition = _definition_json(body.definition)
    await db.commit()
    await db.refresh(form)
    await db.refresh(draft)
    return await _detail(db, form, draft)


async def check_form(db: AsyncSession, workspace_id: uuid.UUID, form_id: uuid.UUID) -> FormCheckOut:
    """Automatic checks of the draft before publishing (POST /forms/{id}/validate): the strict
    FormDefinition rules as errors, plus warnings that do not block."""
    form = await get_form(db, workspace_id, form_id)
    draft = (await repository.get_drafts(db, [form.id])).get(form.id)
    if draft is None:
        raise errors.FormNotEditable()
    draft_definition = DraftFormDefinition.model_validate(draft.definition)
    problems = [
        FormProblem(code=code, message=message, field=path)
        for path, code, message in find_problems(draft_definition)
    ]
    if not problems:
        # Anything the strict model still rejects (should not happen) is reported generically.
        try:
            FormDefinition.model_validate(draft.definition)
        except ValidationError as exc:
            problems = [_problem(e) for e in exc.errors()]
    return FormCheckOut(valid=not problems, errors=problems, warnings=_warnings(draft.definition))


_EMPTY = {
    "label": ("label_required", "Nama isian belum diisi."),
    "question": ("question_required", "Pertanyaan untuk penyuluh belum diisi."),
}


def _problem(error: Any) -> FormProblem:
    loc = tuple(error.get("loc", ()))
    path = ".".join(str(p) for p in loc) or None
    ctx = error.get("ctx") or {}
    if ctx.get("app_code"):
        return FormProblem(code=ctx["app_code"], message=str(error["msg"]), field=path)
    kind = error.get("type", "")
    if loc == ("fields",) and kind == "too_short":
        return FormProblem(code="no_fields", message="Tambahkan minimal satu isian.", field=path)
    if kind in ("string_too_short", "missing") and loc and loc[-1] in _EMPTY:
        if loc[-2:-1] and isinstance(loc[-2], int) and "options" in loc:
            code, message = "option_label_required", "Nama pilihan belum diisi."
        else:
            code, message = _EMPTY[str(loc[-1])]
        return FormProblem(code=code, message=message, field=path)
    return FormProblem(code="invalid_value", message="Isian ini belum benar.", field=path)


def _warnings(definition: dict[str, Any]) -> list[FormProblem]:
    fields = definition.get("fields") or []
    if fields and not any(f.get("role") == "condition" for f in fields):
        return [
            FormProblem(
                code="no_condition_field",
                message=(
                    "Belum ada isian kondisi tanaman. Peta dan ringkasan kondisi di dashboard "
                    "akan kosong untuk struktur ini."
                ),
                field=None,
            )
        ]
    return []


async def publish_form(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, form_id: uuid.UUID
) -> FormDetailOut:
    """The draft becomes the published version new conversations use; it never changes again.
    Refused while the automatic checks find problems."""
    form = await repository.get_form_for_update(db, workspace_id, form_id)
    if form is None:
        raise errors.FormNotFound()
    if form.status == "archived":
        raise errors.FormArchived()
    draft = (await repository.get_drafts(db, [form.id])).get(form.id)
    if draft is None:
        raise errors.FormNotEditable()
    problems = find_problems(DraftFormDefinition.model_validate(draft.definition))
    if problems:
        raise errors.FormHasProblems(len(problems))
    # Store the normalised strict definition: what the engine and reports will read.
    draft.definition = FormDefinition.model_validate(draft.definition).to_json()
    draft.published_at = now_utc()
    draft.published_by_user_id = user_id
    form.current_version_id = draft.id
    form.status = "active"
    await audit.record(
        db,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="form.publish",
        target=str(form.id),
        details={"name": form.name, "version": draft.version},
    )
    await db.commit()
    await db.refresh(form)
    return await _detail(db, form)


async def archive_form(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, form_id: uuid.UUID
) -> FormDetailOut:
    """Stop using a form: no new reports, no more edits. Existing reports stay. Idempotent."""
    form = await repository.get_form_for_update(db, workspace_id, form_id)
    if form is None:
        raise errors.FormNotFound()
    if form.status != "archived":
        form.status = "archived"
        await audit.record(
            db,
            workspace_id=workspace_id,
            actor_user_id=user_id,
            action="form.archive",
            target=str(form.id),
            details={"name": form.name},
        )
        await db.commit()
        await db.refresh(form)
    return await _detail(db, form)


# --- Template catalogue ------------------------------------------------------------------------


async def list_template_catalogue(db: AsyncSession) -> list[FormTemplateSectorOut]:
    sectors = await repository.list_template_sectors(db)
    templates = await repository.list_templates(db)
    by_sector: dict[uuid.UUID, list[FormTemplate]] = {}
    for template in templates:
        by_sector.setdefault(template.sector_id, []).append(template)
    return [
        FormTemplateSectorOut(
            code=s.code,
            name=s.name,
            heading=s.heading,
            chips_label=s.chips_label,
            chips=[TemplateChipOut.model_validate(c) for c in s.chips],
            templates=[
                FormTemplateOut(
                    code=t.code,
                    title=t.title,
                    name=t.name,
                    description=t.description,
                    field_count=t.field_count,
                    minutes=t.minutes,
                )
                for t in by_sector.get(s.id, [])
            ],
        )
        for s in sectors
    ]


async def seed_template_catalogue(db: AsyncSession, sectors: list[dict[str, Any]]) -> int:
    """Insert or update sectors and templates by code (scripts/seed.py templates)."""
    count = 0
    position = 0
    for sector_position, item in enumerate(sectors):
        sector = await repository.get_template_sector_by_code(db, item["code"])
        if sector is None:
            sector = FormTemplateSector(code=item["code"])
            db.add(sector)
        sector.position = sector_position
        sector.name = item["name"]
        sector.heading = item["heading"]
        sector.chips_label = item["chips_label"]
        sector.chips = [TemplateChipOut.model_validate(c).model_dump() for c in item["chips"]]
        await db.flush()
        for t in item["templates"]:
            template = await repository.get_template_by_code(db, t["code"])
            if template is None:
                template = FormTemplate(code=t["code"])
                db.add(template)
            template.sector_id = sector.id
            template.position = position
            template.title = t["title"]
            template.name = t["name"]
            template.description = t["description"]
            template.field_count = t["field_count"]
            template.minutes = t["minutes"]
            position += 1
            count += 1
    await db.commit()
    return count


# --- Helpers ------------------------------------------------------------------------------------


async def _check_settings(db: AsyncSession, settings: FormSettings) -> None:
    await reference_data.check_work_area(
        db, settings.province_id, settings.regency_ids, field_prefix="settings."
    )


def _stored_settings(raw: dict[str, Any] | None) -> FormSettings:
    """Stored settings, ignoring keys an older version wrote (e.g. region_label)."""
    known = FormSettings.model_fields
    return FormSettings.model_validate({k: v for k, v in (raw or {}).items() if k in known})


def _definition_json(definition: FormDefinition | DraftFormDefinition) -> dict[str, Any]:
    return definition.model_dump(mode="json", by_alias=True, exclude_none=True)


def _parse_id(values: list[str] | None) -> uuid.UUID | None:
    if values is None:
        return None
    try:
        return uuid.UUID(values[0])
    except ValueError:
        raise InvalidCursor() from None


def _field_count(version: FormVersion | None) -> int:
    return len(version.definition.get("fields", [])) if version is not None else 0


def _form_out(form: Form, draft: FormVersion | None, current: FormVersion | None) -> FormOut:
    return FormOut(
        id=form.id,
        name=form.name,
        description=form.description,
        status=form.status,  # type: ignore[arg-type]
        current_version_id=form.current_version_id,
        draft_version=draft.version if draft is not None else None,
        current_version=current.version if current is not None else None,
        published_at=current.published_at if current is not None else None,
        field_count=_field_count(draft or current),
        created_at=form.created_at,
        updated_at=form.updated_at,
    )


async def _detail(db: AsyncSession, form: Form, draft: FormVersion | None = None) -> FormDetailOut:
    if draft is None:
        draft = (await repository.get_drafts(db, [form.id])).get(form.id)
    current = None
    if form.current_version_id is not None:
        current = (await repository.get_versions(db, [form.current_version_id])).get(
            form.current_version_id
        )
    base = _form_out(form, draft, current)
    return FormDetailOut(
        **base.model_dump(),
        settings=_stored_settings(form.settings),
        draft=FormDraftOut(
            version_id=draft.id,
            version=draft.version,
            definition=DraftFormDefinition.model_validate(draft.definition),
            updated_at=draft.updated_at,
        )
        if draft is not None
        else None,
    )
