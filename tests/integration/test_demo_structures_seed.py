"""The demo's ready structures: Peternakan in chat mode (location, photos) and the Voice Lab in
voice mode with a sample photo, published with a join code; reruns change nothing, and an older
Voice Lab (no photo) gets a new version instead of a twin."""

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.forms import service as forms
from app.modules.forms.models import Form, FormVersion
from app.modules.forms.schemas import FormDefinition, FormSettings
from app.modules.join_codes import repository as join_code_repo
from app.modules.workspaces.models import Workspace
from scripts import demo_structures

FIXTURE = json.loads(
    (demo_structures.FIXTURES / "demo" / "structures.json").read_text(encoding="utf-8")
)
LIVESTOCK, LAB, SALES = FIXTURE["structures"]


async def _forms(db: AsyncSession, workspace: Workspace) -> dict[str, Form]:
    rows = (await db.scalars(select(Form).where(Form.workspace_id == workspace.id))).all()
    return {f.name: f for f in rows}


async def _definition(db: AsyncSession, form: Form) -> FormDefinition:
    version = await db.get(FormVersion, form.current_version_id)
    assert version is not None and version.published_at is not None
    return FormDefinition.model_validate(version.definition)


async def test_structures_are_published_ready_for_the_bot(
    db: AsyncSession, organization: Workspace, user: User
) -> None:
    await demo_structures.seed_structures(db, organization.id, user.id)

    made = await _forms(db, organization)
    assert set(made) == {LIVESTOCK["name"], LAB["name"], SALES["name"]}
    for form in made.values():
        assert form.status == "active"
        assert await join_code_repo.get_live_for_form(db, organization.id, form.id) is not None

    livestock = made[LIVESTOCK["name"]]
    assert livestock.settings["input_mode"] == "chat"
    types = {f.type for f in (await _definition(db, livestock)).fields}
    assert {"location", "photo"} <= types

    lab = made[LAB["name"]]
    assert lab.settings["input_mode"] == "voice"
    fields = (await _definition(db, lab)).fields
    assert [f.key for f in fields] == ["nomor_sampel", "ph", "suhu", "volume", "foto_sampel"]

    sales = (await _definition(db, made[SALES["name"]])).fields
    assert sales[0].type == "photo" and sales[0].read_values  # the receipt comes first

    # A rerun leaves everything as it is.
    await demo_structures.seed_structures(db, organization.id, user.id)
    count = select(func.count()).select_from(FormVersion)
    assert await db.scalar(count.where(FormVersion.workspace_id == organization.id)) == 3


async def test_older_voice_lab_gets_the_photo_as_a_new_version(
    db: AsyncSession, organization: Workspace, user: User
) -> None:
    older = FormDefinition.model_validate(
        {**LAB["definition"], "fields": LAB["definition"]["fields"][:-1]}  # without the photo
    )
    form = await forms.create_form(
        db, organization.id, user.id, LAB["name"], older,
        settings=FormSettings(input_mode="voice", sector_code="research"),
    )  # fmt: skip
    await forms.publish_form(db, organization.id, user.id, form.id)
    code = await join_code_repo.get_live_for_form(db, organization.id, form.id)
    assert code is not None

    await demo_structures.seed_structures(db, organization.id, user.id)

    same_name = (Form.workspace_id == organization.id) & (Form.name == LAB["name"])
    labs = (await db.scalars(select(Form).where(same_name))).all()
    assert len(labs) == 1 and labs[0].id == form.id
    await db.refresh(labs[0])
    assert (await _definition(db, labs[0])).field("foto_sampel") is not None
    again = await join_code_repo.get_live_for_form(db, organization.id, form.id)
    assert again is not None and again.code == code.code  # workers keep their code
