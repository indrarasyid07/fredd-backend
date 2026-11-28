"""Structures ready for the bot in the demo organization, from `fixtures/demo/structures.json`:
"Laporan Kesehatan Ternak" (chat mode: location, photos), "Uji Sampel Air (Voice Lab)" (voice
mode: one voice note fills the lab values, then a sample photo) and "Catatan Penjualan Hasil
Panen" (chat mode: the receipt photo is read for the other answers, "Baca struk dan foto").

Called by `scripts.seed demo`, or alone with `scripts.seed structures`. Matched by name: a
missing structure is created and published; one whose published definition, description or
settings differ from the fixture gets a new version (same join code, joined workers keep it);
one that already matches is left alone.
"""

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.forms import service as forms_service
from app.modules.forms.schemas import (
    DraftFormDefinition,
    FormDefinition,
    FormDetailOut,
    FormSettings,
    UpdateFormRequest,
)
from app.modules.join_codes import service as join_codes

FIXTURES = Path(__file__).parents[1] / "fixtures"
_LIVE = ("active", "pilot")


async def seed_structures(db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
    data = json.loads((FIXTURES / "demo" / "structures.json").read_text(encoding="utf-8"))
    for item in data["structures"]:
        detail = await _seed_one(db, workspace_id, user_id, item)
        code = await join_codes.get_for_form(db, workspace_id, detail.id, form_status=detail.status)
        link = f"  {code.telegram_url}" if code.telegram_url else ""
        print(f"        join code {code.code}{link}")


async def _seed_one(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, item: dict[str, Any]
) -> FormDetailOut:
    name, description = item["name"], item.get("description")
    definition = FormDefinition.model_validate(item["definition"])
    existing = await _find_live(db, workspace_id, name)
    if existing is None:
        settings = FormSettings.model_validate(item["settings"])
        created = await forms_service.create_form(
            db, workspace_id, user_id, name, definition, description=description, settings=settings
        )
        detail = await forms_service.publish_form(db, workspace_id, user_id, created.id)
        print(f"form '{name}' created and published (v{detail.current_version})")
        return detail

    # Fixture settings on top of the stored ones (work area and the like stay as they are).
    settings = FormSettings.model_validate(
        {**existing.settings.model_dump(mode="json"), **item["settings"]}
    )
    assert existing.current_version_id is not None
    current = await forms_service.get_version_definition(
        db, workspace_id, existing.current_version_id
    )
    if (
        current.definition.to_json() == definition.to_json()
        and existing.settings == settings
        and existing.description == description
    ):
        print(f"form '{name}' up to date (v{existing.current_version})")
        return existing

    await forms_service.open_draft(db, workspace_id, user_id, existing.id)
    await forms_service.update_form(
        db,
        workspace_id,
        existing.id,
        UpdateFormRequest(
            description=description,
            settings=settings,
            definition=DraftFormDefinition.model_validate(definition.to_json()),
        ),
    )
    detail = await forms_service.publish_form(db, workspace_id, user_id, existing.id)
    print(f"form '{name}' updated: v{existing.current_version} -> v{detail.current_version}")
    return detail


async def _find_live(db: AsyncSession, workspace_id: uuid.UUID, name: str) -> FormDetailOut | None:
    """The newest published structure with this name (list_forms is newest first)."""
    forms, _ = await forms_service.list_forms(db, workspace_id, before=None, limit=100)
    for form in forms:
        if form.name == name and form.status in _LIVE and form.current_version_id:
            return await forms_service.get_form_detail(db, workspace_id, form.id)
    return None
