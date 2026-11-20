"""create_report (roadmap 4.0, antarmuka 3): code per workspace and month, filter columns copied
from the answers, photos, completeness, and the region of the point."""

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session as db_session
from app.modules.extension_workers.models import ExtensionWorker
from app.modules.forms import service as forms
from app.modules.forms.models import FormVersion
from app.modules.forms.schemas import FormDefinition
from app.modules.reference_data import service as reference_data
from app.modules.reports import service
from app.modules.reports.models import Report, ReportPhoto
from app.modules.workspaces.models import Workspace
from tests.api.v1.reference_data.test_reference_data import FEATURES
from tests.form_definitions import crop_survey

DEFINITION = FormDefinition.model_validate(crop_survey())

ANSWERS = {
    "location": {"lat": -11.25, "lng": 100.25, "accuracy_m": 12},
    "farmer_name": "Pak Slamet",
    "land_area": "1.5",
    "condition": "infected",
    "photos": ["media/a.jpg", "media/b.jpg"],
}


@pytest.fixture
async def setup(db: AsyncSession, organization: Workspace) -> dict[str, uuid.UUID]:
    form = await forms.create_form(db, organization.id, None, "Survei", DEFINITION)
    version = await db.scalar(select(FormVersion).where(FormVersion.form_id == form.id))
    worker = ExtensionWorker(workspace_id=organization.id, name="Budi", telegram_user_id="1")
    db.add(worker)
    await db.flush()
    assert version is not None
    return {
        "workspace": organization.id,
        "form": form.id,
        "version": version.id,
        "worker": worker.id,
    }


async def _create(db: AsyncSession, ids: dict[str, uuid.UUID], answers: dict, **kw) -> Report:  # noqa: ANN003
    return await service.create_report(
        db,
        workspace_id=ids["workspace"],
        form_id=ids["form"],
        form_version_id=ids["version"],
        definition=DEFINITION,
        extension_worker_id=ids["worker"],
        conversation_id=None,
        answers=answers,
        **kw,
    )


async def test_columns_are_copied_from_the_answers(
    db: AsyncSession, setup: dict[str, uuid.UUID]
) -> None:
    await reference_data.seed_platform_regions(db, FEATURES)
    report = await _create(db, setup, ANSWERS, needs_review=True, review_reasons=["rule:0"])
    assert (report.condition, report.area_ha) == ("infected", Decimal("1.5"))
    assert (report.latitude, report.longitude, report.accuracy_m) == (-11.25, 100.25, 12.0)
    assert report.complete is True
    assert (report.needs_review, report.review_reasons) == (True, ["rule:0"])
    assert report.plot_key is not None and len(report.plot_key) == 32
    region = await reference_data.locate(db, lat=-11.25, lng=100.25)
    assert region.district is not None and report.region_id == region.district.id
    photos = (await db.scalars(select(ReportPhoto).order_by(ReportPhoto.position))).all()
    assert [(p.field_key, p.position, p.object_key) for p in photos] == [
        ("photos", 0, "media/a.jpg"),
        ("photos", 1, "media/b.jpg"),
    ]


async def test_missing_answers_leave_columns_empty(
    db: AsyncSession, setup: dict[str, uuid.UUID]
) -> None:
    answers = {"location": {"name": "Sawah dekat masjid"}, "farmer_name": "", "land_area": "abc"}
    report = await _create(db, setup, answers)
    assert (report.condition, report.area_ha, report.latitude, report.plot_key) == (
        None,
        None,
        None,
        None,
    )
    assert report.region_id is None
    assert report.complete is False  # required fields without an answer
    assert report.review_reasons == []


async def test_codes_count_per_workspace_and_month(
    db: AsyncSession, setup: dict[str, uuid.UUID]
) -> None:
    november = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)
    first = await _create(db, setup, ANSWERS, received_at=november)
    second = await _create(db, setup, ANSWERS, received_at=november)
    # 30 Nov 18:30 UTC is already 1 Dec in Jakarta: the month follows the workspace's zone.
    december = await _create(
        db, setup, ANSWERS, received_at=datetime(2026, 11, 30, 18, 30, tzinfo=UTC)
    )
    assert [first.code, second.code, december.code] == [
        "LP-2611-0001",
        "LP-2611-0002",
        "LP-2612-0001",
    ]

    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    other_form = await forms.create_form(db, other.id, None, "Survei", DEFINITION)
    version = await db.scalar(select(FormVersion).where(FormVersion.form_id == other_form.id))
    worker = ExtensionWorker(workspace_id=other.id, name="Rani", telegram_user_id="2")
    db.add(worker)
    await db.flush()
    assert version is not None
    theirs = await _create(
        db,
        {"workspace": other.id, "form": other_form.id, "version": version.id, "worker": worker.id},
        ANSWERS,
        received_at=november,
    )
    assert theirs.code == "LP-2611-0001"


def test_report_code_grows_past_four_digits() -> None:
    assert service.report_code("2611", 7) == "LP-2611-0007"
    assert service.report_code("2611", 12345) == "LP-2611-12345"


def test_plot_key_groups_points_within_the_grid() -> None:
    worker, form = uuid.uuid4(), uuid.uuid4()
    a = service.plot_key(-6.82140, 107.14020, worker, form)
    near = service.plot_key(-6.82141, 107.14021, worker, form)  # about 1.5 m away
    far = service.plot_key(-6.82300, 107.14020, worker, form)  # about 180 m away
    assert a == near != far
    assert service.plot_key(-6.82140, 107.14020, uuid.uuid4(), form) != a


async def test_parallel_reports_never_share_a_code() -> None:
    """Two sessions creating reports at the same moment get different numbers."""
    async with db_session.open_session() as db:
        ws = Workspace(name="Paralel", type="organization")
        db.add(ws)
        await db.flush()
        form = await forms.create_form(db, ws.id, None, "Survei", DEFINITION)
        version = await db.scalar(select(FormVersion).where(FormVersion.form_id == form.id))
        worker = ExtensionWorker(workspace_id=ws.id, name="Budi", telegram_user_id="9")
        db.add(worker)
        await db.commit()
        assert version is not None
        ids = {"workspace": ws.id, "form": form.id, "version": version.id, "worker": worker.id}

    async def one() -> str:
        async with db_session.open_session() as s:
            report = await _create(s, ids, ANSWERS)
            await s.commit()
            return report.code

    try:
        codes = await asyncio.gather(*[one() for _ in range(5)])
        assert len(set(codes)) == 5
    finally:
        async with db_session.open_session() as db:
            await db.delete(await db.get(Workspace, ws.id))
            await db.commit()
