"""The photo check job (roadmap 12.7) for any kind of structure: the Voice Lab's sample photo is
checked with the form's description and the reported numbers, never its free text."""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai import vision
from app.modules.auth.models import User
from app.modules.extension_workers.models import ExtensionWorker
from app.modules.forms import service as forms
from app.modules.forms.models import FormVersion
from app.modules.forms.schemas import FormDefinition
from app.modules.reports import photo_checks
from app.modules.reports import service as reports
from app.modules.reports.models import ReportPhoto
from app.modules.workspaces.models import Workspace
from scripts import demo_structures
from tests.conftest import MemoryStorage

FIXTURE = json.loads(
    (demo_structures.FIXTURES / "demo" / "structures.json").read_text(encoding="utf-8")
)
LAB = next(s for s in FIXTURE["structures"] if s["settings"]["input_mode"] == "voice")
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60


class FakeChecker:
    name = "fake"

    def __init__(self) -> None:
        self.contexts: list[vision.PhotoContext] = []

    async def check(self, image: bytes, content_type: str, context: vision.PhotoContext) -> str:
        self.contexts.append(context)
        return "Perlu dicek (berbeda dengan laporan): layar alat menunjukkan pH 7,4."


async def test_lab_photo_is_checked_against_the_reported_values(
    db: AsyncSession,
    organization: Workspace,
    user: User,
    media_store: MemoryStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = FormDefinition.model_validate(LAB["definition"])
    form = await forms.create_form(
        db, organization.id, user.id, LAB["name"], definition, description=LAB["description"]
    )
    await forms.publish_form(db, organization.id, user.id, form.id)  # checks need a published one
    version = await db.scalar(select(FormVersion).where(FormVersion.form_id == form.id))
    worker = ExtensionWorker(workspace_id=organization.id, name="Budi", telegram_user_id="1")
    db.add(worker)
    await db.flush()
    assert version is not None
    key = f"workspaces/{organization.id}/messages/sample.jpg"
    await media_store.put(key, JPEG, "image/jpeg")
    report = await reports.create_report(
        db,
        workspace_id=organization.id,
        form_id=form.id,
        form_version_id=version.id,
        definition=definition,
        extension_worker_id=worker.id,
        conversation_id=None,
        answers={"nomor_sampel": "S-2041", "ph": "6.8", "suhu": "25", "foto_sampel": [key]},
    )
    checker = FakeChecker()
    monkeypatch.setattr(vision, "override", checker)

    assert await photo_checks.check_report_photos(db, organization.id, report.id) == 1

    (context,) = checker.contexts
    assert context.form_name == LAB["name"]
    assert context.form_description == LAB["description"]
    assert context.field_label == "Foto sampel"
    assert list(context.answers) == ["pH: 6,8", "Suhu: 25 °C"]  # no free text (sample, names)
    photo = await db.scalar(select(ReportPhoto))
    assert photo is not None and photo.ai_note is not None and "7,4" in photo.ai_note
