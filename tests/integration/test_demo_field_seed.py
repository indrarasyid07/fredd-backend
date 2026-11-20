"""The demo field data (ROADMAP 4.1): a published structure, 12 workers in 6 regencies and ~150
reports over 14 days, every report inside a known region, and nothing doubled on a rerun."""

import gzip
import json
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.auth.models import User
from app.modules.extension_workers.models import ExtensionWorker, FormAssignment
from app.modules.forms.models import Form
from app.modules.reference_data import service as reference_data
from app.modules.reports.models import Report, ReportPhoto
from app.modules.workspaces.models import Workspace
from scripts import demo_field
from tests.conftest import MemoryStorage

FIELD = json.loads((demo_field.FIXTURES / "demo" / "field.json").read_text(encoding="utf-8"))


async def _west_java_regions(db: AsyncSession) -> None:
    """Only the regions the demo uses (the whole country is slow to load in every test)."""
    districts = {w["district"] for w in FIELD["workers"]}
    keep = districts | {d.rsplit(".", 1)[0] for d in districts} | {"32"}
    path = demo_field.FIXTURES / "reference" / "regions.geojson.gz"
    with gzip.open(path, "rt", encoding="utf-8") as f:
        features = [x for x in json.load(f)["features"] if x["properties"]["code"] in keep]
    await reference_data.seed_platform_regions(db, features)


async def _count(db: AsyncSession, model: type, *where: Any) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*where)) or 0


async def test_demo_field_data(
    db: AsyncSession, organization: Workspace, user: User, media_store: MemoryStorage
) -> None:
    await _west_java_regions(db)
    await demo_field.seed_field(db, organization.id, user.id)

    form = await db.scalar(select(Form).where(Form.workspace_id == organization.id))
    assert form is not None and form.status == "active" and form.current_version_id
    workers = (
        await db.scalars(
            select(ExtensionWorker).where(ExtensionWorker.workspace_id == organization.id)
        )
    ).all()
    assert len(workers) == 12
    assert all(w.phone_e164 and w.phone_e164.startswith("+628110000") for w in workers)
    assert all(w.status == "active" and w.confirmed_at and w.region_id for w in workers)
    assert {w.telegram_user_id is None for w in workers} == {True, False}  # both channels
    assert await _count(db, FormAssignment, FormAssignment.form_id == form.id) == 12

    reports = (await db.scalars(select(Report).where(Report.workspace_id == organization.id))).all()
    # ~150: today's share depends on the hour the test runs.
    assert 110 <= len(reports) <= 150
    now = now_utc()
    assert all(now - timedelta(days=14) < r.received_at <= now for r in reports)
    assert all(r.region_id and r.condition and r.area_ha is not None for r in reports)
    assert {r.condition for r in reports} == {"healthy", "attention", "infected"}
    today = now.astimezone(ZoneInfo("Asia/Jakarta")).date()
    reported_today = {
        r.extension_worker_id
        for r in reports
        if r.received_at.astimezone(ZoneInfo("Asia/Jakarta")).date() == today
    }
    assert len(reported_today) <= demo_field.ACTIVE_TODAY
    assert all(r.needs_review == (r.area_ha is not None and r.area_ha > 50) for r in reports)
    # Photos point at the sample files stored under the organization.
    keys = {p.object_key for p in (await db.scalars(select(ReportPhoto))).all()}
    assert keys and keys <= set(media_store.objects)
    assert all(k.startswith(f"workspaces/{organization.id}/demo/") for k in keys)

    # A rerun reuses everything and adds nothing.
    await demo_field.seed_field(db, organization.id, user.id)
    assert await _count(db, Form, Form.workspace_id == organization.id) == 1
    assert await _count(db, ExtensionWorker, ExtensionWorker.workspace_id == organization.id) == 12
    assert await _count(db, Report, Report.workspace_id == organization.id) == len(reports)


async def test_without_regions_nothing_is_made(
    db: AsyncSession, organization: Workspace, user: User
) -> None:
    await demo_field.seed_field(db, organization.id, user.id)
    assert await _count(db, ExtensionWorker, ExtensionWorker.workspace_id == organization.id) == 0
    assert await _count(db, Report) == 0
