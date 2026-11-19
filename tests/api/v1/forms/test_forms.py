"""Wizard endpoints: create a draft, autosave it, read it back, list forms, template catalogue."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.forms import service
from app.modules.forms.models import FormVersion
from app.modules.forms.schemas import FormDefinition
from app.modules.workspaces.models import Workspace
from tests.conftest import add_member, sign_in
from tests.form_definitions import crop_survey

URL = "/api/v1/forms"
FIXTURE = Path(__file__).parents[4] / "fixtures" / "templates" / "form_templates.json"


@pytest.fixture
async def editor(client: AsyncClient, db: AsyncSession, organization: Workspace) -> AsyncClient:
    await add_member(db, organization.id, email="fajar@contoh.id", role="form_editor")
    return await sign_in(client, "fajar@contoh.id", organization.id)


async def _as(client: AsyncClient, db: AsyncSession, org: Workspace, role: str) -> AsyncClient:
    email = f"{role}@contoh.id"
    await add_member(db, org.id, email=email, role=role)
    return await sign_in(client, email, org.id)


async def test_create_then_read_the_draft(editor: AsyncClient) -> None:
    body = {
        "name": "Survei Kondisi Tanaman",
        "definition": crop_survey(),
        "settings": {"template_code": "00", "sector_code": "agriculture", "commodities": ["Padi"]},
    }
    created = await editor.post(URL, json=body)
    assert created.status_code == 200
    data = created.json()["data"]
    assert (data["status"], data["draft_version"], data["field_count"]) == ("draft", 1, 5)
    assert data["settings"]["frequency"] == "weekly"  # default filled in

    read = (await editor.get(f"{URL}/{data['id']}")).json()["data"]
    assert read["draft"]["definition"]["fields"][3]["role"] == "condition"
    assert read["settings"]["commodities"] == ["Padi"]


async def test_draft_may_be_incomplete(editor: AsyncClient) -> None:
    """Autosave must not fail while someone is still typing."""
    body = {"name": "Baru", "definition": {"fields": [{"key": "a", "type": "short_text"}]}}
    response = await editor.post(URL, json=body)
    assert response.status_code == 200
    assert response.json()["data"]["draft"]["definition"]["fields"][0]["question"] == ""

    empty = await editor.post(URL, json={"name": "Kosong"})
    assert empty.json()["data"]["field_count"] == 0


async def test_shape_errors_are_still_rejected(editor: AsyncClient) -> None:
    body = {"name": "X", "definition": {"fields": [{"key": "A B", "type": "radio"}]}}
    response = await editor.post(URL, json=body)
    assert response.status_code == 422
    fields = {e["field"] for e in response.json()["errors"]}
    assert fields == {"definition.fields.0.key", "definition.fields.0.type"}


async def test_autosave_changes_only_what_is_sent(editor: AsyncClient) -> None:
    form = (await editor.post(URL, json={"name": "Awal", "description": "D"})).json()["data"]

    patch = {"definition": crop_survey(), "settings": {"frequency": "daily"}}
    response = await editor.patch(f"{URL}/{form['id']}", json=patch)
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["name"], data["description"], data["field_count"]) == ("Awal", "D", 5)
    assert data["settings"]["frequency"] == "daily"

    data = (await editor.patch(f"{URL}/{form['id']}", json={"description": None})).json()["data"]
    assert data["description"] is None and data["field_count"] == 5


async def test_published_form_without_draft_is_not_editable(
    editor: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    form = await service.create_form(
        db, organization.id, None, "Terbit", FormDefinition.model_validate(crop_survey())
    )
    version = await db.scalar(select(FormVersion).where(FormVersion.form_id == form.id))
    assert version is not None
    version.published_at = now_utc()
    form.status, form.current_version_id = "active", version.id
    await db.flush()

    response = await editor.patch(f"{URL}/{form.id}", json={"name": "Ubah"})
    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "form_not_editable"
    listed = (await editor.get(URL)).json()["data"]
    assert (listed[0]["draft_version"], listed[0]["field_count"]) == (None, 5)


async def test_list_is_newest_first_with_cursor(editor: AsyncClient) -> None:
    for name in ("Satu", "Dua", "Tiga"):
        await editor.post(URL, json={"name": name})
    first = (await editor.get(URL, params={"limit": 2})).json()
    assert [f["name"] for f in first["data"]] == ["Tiga", "Dua"]
    cursor = first["meta"]["pagination"]["next_cursor"]
    second = (await editor.get(URL, params={"limit": 2, "cursor": cursor})).json()
    assert [f["name"] for f in second["data"]] == ["Satu"]
    assert second["meta"]["pagination"]["has_more"] is False


async def test_reviewer_reads_but_cannot_write(
    client: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    form = await service.create_form(
        db, organization.id, None, "S", FormDefinition.model_validate(crop_survey())
    )
    reviewer = await _as(client, db, organization, "reviewer")
    assert (await reviewer.get(f"{URL}/{form.id}")).status_code == 200
    for response in (
        await reviewer.post(URL, json={"name": "X"}),
        await reviewer.patch(f"{URL}/{form.id}", json={"name": "X"}),
    ):
        assert response.status_code == 403


async def test_other_workspace_form_is_not_found(
    editor: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    form = await service.create_form(
        db, other.id, None, "Rahasia", FormDefinition.model_validate(crop_survey())
    )
    for response in (
        await editor.get(f"{URL}/{form.id}"),
        await editor.patch(f"{URL}/{form.id}", json={"name": "X"}),
    ):
        assert response.status_code == 404
        assert response.json()["errors"][0]["code"] == "form_not_found"
    assert (await editor.get(URL)).json()["data"] == []


async def test_needs_a_session(client: AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401


async def test_template_catalogue(editor: AsyncClient, db: AsyncSession) -> None:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    await service.seed_template_catalogue(db, data["sectors"])
    await service.seed_template_catalogue(db, data["sectors"])  # idempotent

    sectors = (await editor.get("/api/v1/form-templates")).json()["data"]
    assert [s["code"] for s in sectors][:2] == ["agriculture", "livestock"]
    assert sum(len(s["templates"]) for s in sectors) == 25
    first = sectors[0]["templates"][0]
    assert (first["code"], first["name"], first["field_count"]) == (
        "00",
        "Survei Kondisi Tanaman",
        8,
    )
    assert sectors[0]["chips"][0] == {"label": "Padi", "default_on": True}


def _region(code: str, x0: float) -> dict[str, Any]:
    ring = [[x0, -12.0], [x0 + 0.5, -12.0], [x0 + 0.5, -11.0], [x0, -11.0], [x0, -12.0]]
    return {
        "type": "Feature",
        "properties": {"code": code, "name": f"Wilayah {code}", "centroid": [x0, -11.5]},
        "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]},
    }


@pytest.fixture
async def regions(db: AsyncSession) -> dict[str, str]:
    from app.modules.reference_data import service as reference_data
    from app.modules.reference_data.models import ReferenceData

    features = [
        _region("98", 100.0),
        _region("98.01", 100.0),
        _region("97", 102.0),
        _region("97.01", 102.0),
    ]
    await reference_data.seed_platform_regions(db, features)
    rows = await db.scalars(
        select(ReferenceData).where(ReferenceData.code.in_(["98", "98.01", "97", "97.01"]))
    )
    return {r.code: str(r.id) for r in rows if r.code}


async def test_work_area_is_saved_by_id(editor: AsyncClient, regions: dict[str, str]) -> None:
    settings = {"province_id": regions["98"], "regency_ids": [regions["98.01"]]}
    response = await editor.post(URL, json={"name": "A", "settings": settings})
    assert response.status_code == 200
    saved = response.json()["data"]["settings"]
    assert (saved["province_id"], saved["regency_ids"]) == (regions["98"], [regions["98.01"]])


@pytest.mark.parametrize(
    ("settings", "field"),
    [
        ({"province_id": "98.01", "regency_ids": []}, "settings.province_id"),  # a regency
        ({"province_id": "98", "regency_ids": ["97.01"]}, "settings.regency_ids.0"),  # elsewhere
        ({"province_id": None, "regency_ids": ["98.01"]}, "settings.regency_ids.0"),
    ],
)
async def test_work_area_must_match_reference_data(
    editor: AsyncClient, regions: dict[str, str], settings: dict[str, Any], field: str
) -> None:
    def resolve(code: str | None) -> str | None:
        return regions[code] if code else None

    body = {
        "name": "A",
        "settings": {
            "province_id": resolve(settings["province_id"]),
            "regency_ids": [resolve(c) for c in settings["regency_ids"]],
        },
    }
    response = await editor.post(URL, json=body)
    assert response.status_code == 422
    error = response.json()["errors"][0]
    assert (error["code"], error["field"]) == ("unknown_region", field)


async def test_old_settings_keys_are_ignored(
    editor: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    form = await service.create_form(
        db, organization.id, None, "Lama", FormDefinition.model_validate(crop_survey())
    )
    form.settings = {"region_label": "Jawa Barat · 6 kabupaten", "frequency": "daily"}
    await db.flush()
    data = (await editor.get(f"{URL}/{form.id}")).json()["data"]
    assert data["settings"]["frequency"] == "daily"
    assert "region_label" not in data["settings"]


async def _draft(editor: AsyncClient, definition: dict[str, Any]) -> str:
    response = await editor.post(URL, json={"name": "Cek", "definition": definition})
    return response.json()["data"]["id"]


async def test_validate_a_complete_draft(editor: AsyncClient) -> None:
    form_id = await _draft(editor, crop_survey())
    response = await editor.post(f"{URL}/{form_id}/validate")
    assert response.status_code == 200
    assert response.json()["data"] == {"valid": True, "errors": [], "warnings": []}


async def test_validate_reports_each_problem_with_its_field(editor: AsyncClient) -> None:
    definition = crop_survey()
    definition["fields"][1]["question"] = ""  # empty question
    definition["fields"][2]["label"] = "Lokasi lahan"  # twin of field 0
    definition["fields"][3]["options"][2]["label"] = "Sehat"  # twin option label
    definition["rules"][0]["then"]["require"] = "missing_field"
    form_id = await _draft(editor, definition)

    data = (await editor.post(f"{URL}/{form_id}/validate")).json()["data"]
    assert data["valid"] is False
    found = sorted((e["field"], e["code"]) for e in data["errors"])
    assert found == [
        ("fields.1.question", "question_required"),
        ("fields.2.label", "duplicate_field_label"),
        ("fields.3.options.2.label", "duplicate_option_label"),
        ("rules.0.then.require", "unknown_field"),
    ]
    assert all(e["message"] for e in data["errors"])


async def test_validate_empty_and_unlabelled(editor: AsyncClient) -> None:
    empty = await _draft(editor, {"fields": []})
    data = (await editor.post(f"{URL}/{empty}/validate")).json()["data"]
    assert [(e["field"], e["code"]) for e in data["errors"]] == [("fields", "no_fields")]

    blank = {
        "fields": [
            {
                "key": "a",
                "type": "single_choice",
                "options": [{"value": "x", "label": ""}, {"value": "y", "label": "Y"}],
            }
        ]
    }
    data = (await editor.post(f"{URL}/{await _draft(editor, blank)}/validate")).json()["data"]
    codes = {(e["field"], e["code"]) for e in data["errors"]}
    assert ("fields.0.label", "label_required") in codes
    assert ("fields.0.question", "question_required") in codes
    assert ("fields.0.options.0.label", "option_label_required") in codes


async def test_missing_condition_field_is_only_a_warning(editor: AsyncClient) -> None:
    definition = crop_survey()
    definition["fields"][3].pop("role")
    data = (await editor.post(f"{URL}/{await _draft(editor, definition)}/validate")).json()["data"]
    assert data["valid"] is True
    assert [w["code"] for w in data["warnings"]] == ["no_condition_field"]


async def test_validate_needs_editor_and_own_workspace(
    client: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    form = await service.create_form(
        db, organization.id, None, "S", FormDefinition.model_validate(crop_survey())
    )
    reviewer = await _as(client, db, organization, "reviewer")
    assert (await reviewer.post(f"{URL}/{form.id}/validate")).status_code == 403
    other = Workspace(name="Lain", type="organization")
    db.add(other)
    await db.flush()
    elsewhere = await service.create_form(
        db, other.id, None, "S", FormDefinition.model_validate(crop_survey())
    )
    editor = await _as(client, db, organization, "form_editor")
    assert (await editor.post(f"{URL}/{elsewhere.id}/validate")).status_code == 404


@pytest.fixture
async def admin(client: AsyncClient, user: Any, organization: Workspace) -> AsyncClient:
    """The `user` fixture (Dina) is admin of `organization`."""
    return await sign_in(client, user.email, organization.id)


async def test_publish_makes_the_draft_the_current_version(
    admin: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    from app.modules.audit.models import AuditLog

    form_id = await _draft(admin, crop_survey())
    response = await admin.post(f"{URL}/{form_id}/publish")
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["status"], data["draft"], data["draft_version"]) == ("active", None, None)
    assert (data["current_version"], data["field_count"]) == (1, 5)
    assert data["published_at"] is not None

    listed = (await admin.get(URL)).json()["data"][0]
    assert (listed["status"], listed["current_version"]) == ("active", 1)
    published = await service.get_version_definition(
        db, organization.id, uuid.UUID(data["current_version_id"])
    )
    assert published.definition.field_with_role("condition") is not None
    log = await db.scalar(select(AuditLog).where(AuditLog.action == "form.publish"))
    assert log is not None and log.target == form_id

    # A published version never changes: no draft to edit, no second publish.
    assert (await admin.patch(f"{URL}/{form_id}", json={"name": "X"})).status_code == 409
    again = await admin.post(f"{URL}/{form_id}/publish")
    assert again.json()["errors"][0]["code"] == "form_not_editable"


async def test_publish_refuses_a_draft_with_problems(admin: AsyncClient) -> None:
    definition = crop_survey()
    definition["fields"][0]["question"] = ""
    form_id = await _draft(admin, definition)
    response = await admin.post(f"{URL}/{form_id}/publish")
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "form_has_problems"
    assert (await admin.get(f"{URL}/{form_id}")).json()["data"]["status"] == "draft"


async def test_only_admins_publish_and_archive(editor: AsyncClient) -> None:
    form_id = await _draft(editor, crop_survey())
    assert (await editor.post(f"{URL}/{form_id}/publish")).status_code == 403
    assert (await editor.post(f"{URL}/{form_id}/archive")).status_code == 403


async def test_archive_stops_editing_and_is_idempotent(admin: AsyncClient) -> None:
    form_id = await _draft(admin, crop_survey())
    first = await admin.post(f"{URL}/{form_id}/archive")
    assert first.json()["data"]["status"] == "archived"
    assert (await admin.post(f"{URL}/{form_id}/archive")).status_code == 200
    patch = await admin.patch(f"{URL}/{form_id}", json={"name": "X"})
    assert (patch.status_code, patch.json()["errors"][0]["code"]) == (409, "form_archived")
    publish = await admin.post(f"{URL}/{form_id}/publish")
    assert publish.json()["errors"][0]["code"] == "form_archived"


async def test_publish_other_workspace_is_not_found(admin: AsyncClient, db: AsyncSession) -> None:
    other = Workspace(name="Lain", type="organization")
    db.add(other)
    await db.flush()
    form = await service.create_form(
        db, other.id, None, "S", FormDefinition.model_validate(crop_survey())
    )
    assert (await admin.post(f"{URL}/{form.id}/publish")).status_code == 404
    assert (await admin.post(f"{URL}/{form.id}/archive")).status_code == 404
