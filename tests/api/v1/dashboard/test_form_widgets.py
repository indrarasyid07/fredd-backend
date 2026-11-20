"""Generic widget data per structure (roadmap 4.7, D17): choice and number answers are copied to
report_values, and GET /dashboard/forms/{id} adds them up for any field, any sector."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.dashboard import service
from app.modules.extension_workers.models import ExtensionWorker
from app.modules.forms import service as forms
from app.modules.forms.models import Form, FormVersion
from app.modules.forms.schemas import DraftFormDefinition, FormDefinition, find_problems
from app.modules.reports import service as reports
from app.modules.reports.models import ReportValue
from app.modules.workspaces.models import Workspace
from tests.conftest import add_member, sign_in

NOW = datetime(2026, 11, 18, 3, 30, tzinfo=UTC)  # 10:30 in Jakarta
TODAY = NOW - timedelta(hours=1)
LAB = {
    "fields": [
        {"key": "sample", "type": "short_text", "label": "Nomor sampel", "question": "Nomor?"},
        {"key": "ph", "type": "number", "label": "pH", "question": "pH?", "role": "measure"},
        {"key": "temp", "type": "number", "label": "Suhu", "question": "Suhu?", "unit": "°C",
         "role": "measure"},
        {"key": "status", "type": "single_choice", "label": "Status sampel", "question": "Status?",
         "role": "status",
         "options": [{"value": "ok", "label": "Lolos"}, {"value": "fail", "label": "Gagal"},
                     {"value": "redo", "label": "Ulang"}]},
        {"key": "tests", "type": "multi_choice", "label": "Uji", "question": "Uji apa?",
         "required": False,
         "options": [{"value": "micro", "label": "Mikroba"}, {"value": "heavy", "label": "Logam"}]},
    ],
    "rules": [],
}  # fmt: skip


async def _lab(db: AsyncSession, workspace: Workspace) -> tuple[Form, uuid.UUID, Any]:
    definition = FormDefinition.model_validate(LAB)
    form = await forms.create_form(db, workspace.id, None, "Uji Sampel Air", definition)
    version = await db.scalar(select(FormVersion).where(FormVersion.form_id == form.id))
    assert version is not None
    version.published_at = NOW
    form.current_version_id, form.status = version.id, "active"
    worker = ExtensionWorker(workspace_id=workspace.id, name="Rina", telegram_user_id="9")
    db.add(worker)
    await db.flush()

    async def report(at: datetime = TODAY, **answers: Any) -> Any:
        return await reports.create_report(
            db,
            workspace_id=workspace.id,
            form_id=form.id,
            form_version_id=version.id,
            definition=definition,
            extension_worker_id=worker.id,
            conversation_id=None,
            answers={"sample": "S-1", **answers},
            received_at=at,
        )

    return form, version.id, report


async def test_choice_and_number_answers_are_copied(
    db: AsyncSession, organization: Workspace
) -> None:
    _, _, report = await _lab(db, organization)
    made = await report(ph="6.8", temp="25", status="ok", tests=["micro", "heavy"])
    await report(ph="abc", status=None)  # not a number: left out, never guessed
    rows = (await db.scalars(select(ReportValue).where(ReportValue.report_id == made.id))).all()
    got = sorted(
        (r.field_key, r.choice, f"{r.number.normalize():f}" if r.number is not None else None)
        for r in rows
    )
    assert got == [
        ("ph", None, "6.8"),
        ("status", "ok", None),
        ("temp", None, "25"),
        ("tests", "heavy", None),
        ("tests", "micro", None),
    ]
    assert all(r.received_at == made.received_at and r.form_id == made.form_id for r in rows)


async def test_every_field_adds_up(db: AsyncSession, organization: Workspace) -> None:
    form, _, report = await _lab(db, organization)
    await report(ph="6.5", temp="24", status="ok", tests=["micro"])
    await report(ph="7.0", temp="26", status="ok", tests=["micro", "heavy"])
    await report(ph="7.5", status="fail")
    await report(at=TODAY - timedelta(days=3), ph="9", status="redo")  # outside "today"

    data = await service.form_dashboard(db, organization.id, form.id, "today", now=NOW)
    assert (data.total, data.form.name) == (3, "Uji Sampel Air")
    assert [d.count for d in data.daily] == [0, 0, 0, 1, 0, 0, 3]
    by_key = {f.key: f for f in data.fields}
    assert list(by_key) == ["ph", "temp", "status", "tests"]  # version order, text left out

    ph = by_key["ph"]
    assert (ph.role, ph.answered) == ("measure", 3)
    assert ph.numbers is not None
    assert (ph.numbers.sum, ph.numbers.avg, ph.numbers.min, ph.numbers.max) == (21, 7, 6.5, 7.5)
    assert by_key["temp"].unit == "°C" and by_key["temp"].numbers.count == 2  # type: ignore[union-attr]

    status = by_key["status"]
    assert [(c.label, c.count, c.percent) for c in status.choices or []] == [
        ("Lolos", 2, 67),
        ("Gagal", 1, 33),
        ("Ulang", 0, 0),
    ]
    # Several choices per report: the share of reports that answered, not of choices.
    tests = by_key["tests"]
    assert tests.answered == 2
    assert [(c.label, c.count, c.percent) for c in tests.choices or []] == [
        ("Mikroba", 2, 100),
        ("Logam", 1, 50),
    ]

    week = await service.form_dashboard(db, organization.id, form.id, "7d", now=NOW)
    assert week.total == 4
    assert [c.count for c in next(f for f in week.fields if f.key == "status").choices or []] == [
        2,
        1,
        1,
    ]


async def test_values_of_an_older_version_still_count(
    db: AsyncSession, organization: Workspace
) -> None:
    form, _, report = await _lab(db, organization)
    await report(status="pending")  # an option a later version removed
    data = await service.form_dashboard(db, organization.id, form.id, now=NOW)
    status = next(f for f in data.fields if f.key == "status")
    assert [(c.value, c.label, c.count) for c in status.choices or []][-1] == (
        "pending",
        "pending",
        1,
    )


async def test_api_and_workspace_boundary(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    form, _, report = await _lab(db, organization)
    await report(at=datetime.now(UTC) - timedelta(minutes=1), ph="7", status="ok")
    await sign_in(client, user.email, organization.id)
    body = (await client.get(f"/api/v1/dashboard/forms/{form.id}")).json()
    assert body["success"] and body["data"]["total"] == 1
    assert [f["key"] for f in body["data"]["fields"]] == ["ph", "temp", "status", "tests"]

    other = Workspace(name="Lab Lain", type="organization")
    db.add(other)
    await db.flush()
    await add_member(db, other.id, email="rani@contoh.id", role="reviewer")
    await sign_in(client, "rani@contoh.id", other.id)
    missing = await client.get(f"/api/v1/dashboard/forms/{form.id}")
    assert missing.status_code == 404


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"key": "ph", "role": "status"}, "status_not_choice"),
        ({"key": "status", "role": "measure"}, "measure_not_number"),
    ],
)
def test_role_must_fit_the_field_type(change: dict[str, str], code: str) -> None:
    definition: dict[str, Any] = {
        **LAB,
        "fields": [
            {**f, "role": change["role"]} if f["key"] == change["key"] else f for f in LAB["fields"]
        ],
    }
    assert code in [c for _, c, _ in find_problems(DraftFormDefinition.model_validate(definition))]


def test_several_measures_are_fine_but_one_condition() -> None:
    assert find_problems(DraftFormDefinition.model_validate(LAB)) == []
