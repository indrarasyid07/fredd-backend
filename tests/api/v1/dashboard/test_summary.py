"""GET /dashboard/summary (roadmap 4.2) against dashboard.md "Definisi angka" and its required
tests: workspace isolation, 7 daily entries, day boundaries in Asia/Jakarta, a null change when
yesterday had none, percents adding up to 100, and the regency of a district's report."""

from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.dashboard import service
from app.modules.dashboard.service import largest_remainder
from app.modules.extension_workers.models import ExtensionWorker
from app.modules.reference_data import service as reference_data
from app.modules.workspaces.models import Workspace
from tests.api.v1.reference_data.test_reference_data import FEATURES
from tests.api.v1.reports.test_reports import ANSWERS, Topic, _topic
from tests.conftest import add_member, sign_in

URL = "/api/v1/dashboard/summary"
# 10:30 in Jakarta on 18 November 2026 (UTC+7).
NOW = datetime(2026, 11, 18, 3, 30, tzinfo=UTC)
WEST = {"lat": -11.25, "lng": 100.25, "accuracy_m": 5}  # Kecamatan Utara, Kabupaten Barat
EAST = {"lat": -11.5, "lng": 100.75, "accuracy_m": 5}  # Kabupaten Timur (no district)


def jakarta(day: int, hour: int, minute: int = 0) -> datetime:
    """A November 2026 instant given in Jakarta time."""
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC) - timedelta(hours=7)


async def _report(db: AsyncSession, topic: Topic, at: datetime, **answers: Any) -> None:
    await topic.report(db, {**ANSWERS, **answers}, received_at=at)


async def test_reports_today_and_change(db: AsyncSession, organization: Workspace) -> None:
    topic = await _topic(db, organization)
    for at in (jakarta(18, 7), jakarta(18, 9), jakarta(18, 10, 15)):
        await _report(db, topic, at)
    await _report(db, topic, jakarta(17, 8))
    await _report(db, topic, jakarta(17, 12))  # after 10:30 yesterday: not "same time"
    kpi = (await service.summary(db, organization.id, now=NOW)).kpis.reports_today
    assert (kpi.value, kpi.yesterday_same_time, kpi.delta_pct) == (3, 1, 200.0)


async def test_change_is_null_without_reports_yesterday(
    db: AsyncSession, organization: Workspace
) -> None:
    topic = await _topic(db, organization)
    await _report(db, topic, jakarta(18, 8))
    kpi = (await service.summary(db, organization.id, now=NOW)).kpis.reports_today
    assert (kpi.value, kpi.yesterday_same_time, kpi.delta_pct) == (1, 0, None)


async def test_days_end_at_midnight_in_jakarta(db: AsyncSession, organization: Workspace) -> None:
    topic = await _topic(db, organization)
    await _report(db, topic, jakarta(17, 23, 59))
    await _report(db, topic, jakarta(18, 0, 1))
    summary = await service.summary(db, organization.id, now=NOW)
    assert summary.kpis.reports_today.value == 1
    assert [d.count for d in summary.daily][-2:] == [1, 1]


async def test_daily_is_always_seven_days_with_zeros(
    db: AsyncSession, organization: Workspace
) -> None:
    topic = await _topic(db, organization)
    await _report(db, topic, jakarta(15, 9))
    await _report(db, topic, jakarta(9, 9))  # the week before: the comparison line
    summary = await service.summary(db, organization.id, now=NOW)
    assert [d.date.isoformat() for d in summary.daily] == [f"2026-11-{d}" for d in range(12, 19)]
    assert [d.count for d in summary.daily] == [0, 0, 0, 1, 0, 0, 0]
    assert [d.date.day for d in summary.previous_daily] == list(range(5, 12))
    assert [d.count for d in summary.previous_daily] == [0, 0, 0, 0, 1, 0, 0]
    assert summary.kpis.reports_today.trend == [d.count for d in summary.daily]


async def test_workers_completion_and_channels(db: AsyncSession, organization: Workspace) -> None:
    topic = await _topic(db, organization)
    whatsapp = ExtensionWorker(
        workspace_id=organization.id, name="Siti", phone_e164="+6281100000901"
    )
    idle = ExtensionWorker(workspace_id=organization.id, name="Yusuf", phone_e164="+6281100000902")
    db.add_all([whatsapp, idle])
    await db.flush()
    await _report(db, topic, jakarta(18, 8))
    await _report(db, topic, jakarta(18, 9), farmer_name=None)  # a required answer missing
    whatsapp_topic = Topic(topic.workspace, topic.form, topic.version, whatsapp)
    await _report(db, whatsapp_topic, jakarta(18, 9))
    await _report(db, whatsapp_topic, jakarta(16, 9))

    kpis = (await service.summary(db, organization.id, now=NOW)).kpis
    assert (kpis.workers.active, kpis.workers.total, kpis.workers.not_reported) == (2, 3, 1)
    assert kpis.completion.percent == 67  # 2 of 3 complete
    summary = await service.summary(db, organization.id, now=NOW)
    assert (summary.channels.telegram, summary.channels.whatsapp) == (50, 50)


async def test_conditions_follow_range_and_add_up_to_100(
    db: AsyncSession, organization: Workspace
) -> None:
    topic = await _topic(db, organization)
    for condition in ("healthy", "attention", "infected"):
        await _report(db, topic, jakarta(18, 8), condition=condition)
    await _report(db, topic, jakarta(18, 8), condition=None)
    await _report(db, topic, jakarta(14, 8), condition="infected")

    today = (await service.summary(db, organization.id, "today", now=NOW)).conditions
    assert [(i.key, i.count, i.percent) for i in today.items] == [
        ("healthy", 1, 34),
        ("attention", 1, 33),
        ("infected", 1, 33),
    ]
    assert (today.total, today.unknown) == (3, 1)
    week = (await service.summary(db, organization.id, "7d", now=NOW)).conditions
    assert [i.count for i in week.items] == [1, 1, 2]
    assert sum(i.percent for i in week.items) == 100


def test_largest_remainder() -> None:
    assert largest_remainder([74, 35, 19]) == [58, 27, 15]
    assert largest_remainder([2, 2, 2]) == [34, 33, 33]
    assert largest_remainder([0, 0]) == [0, 0]
    assert largest_remainder([1, 0]) == [100, 0]


async def test_regions_and_land_by_regency(db: AsyncSession, organization: Workspace) -> None:
    await reference_data.seed_platform_regions(db, FEATURES)
    topic = await _topic(db, organization)
    # Two visits to the same plot: only the newest counts for the land.
    await _report(db, topic, jakarta(18, 7), location=WEST, land_area="2", condition="infected")
    await _report(db, topic, jakarta(18, 9), location=WEST, land_area="3", condition="infected")
    await _report(db, topic, jakarta(18, 9), location=EAST, land_area="1.5", condition="healthy")

    summary = await service.summary(db, organization.id, now=NOW)
    land = summary.kpis.monitored_land
    assert (land.area_ha, land.points, land.regencies) == (4.5, 2, 2)
    assert [(r.name, r.count) for r in summary.top_regions] == [
        ("Kabupaten Barat", 2),
        ("Kabupaten Timur", 1),
    ]
    assert [(r.name, r.count) for r in summary.conditions.top_infected_regions] == [
        ("Kabupaten Barat", 2)
    ]


async def test_other_workspace_sees_nothing(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    topic = await _topic(db, organization)
    await _report(db, topic, datetime.now(UTC) - timedelta(minutes=1))
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    await add_member(db, other.id, email="rani@contoh.id", role="reviewer")
    await sign_in(client, "rani@contoh.id", other.id)
    body = (await client.get(URL, params={"range": "7d"})).json()
    assert body["success"] and body["errors"] == []
    data = body["data"]
    assert data["kpis"]["reports_today"]["value"] == 0
    assert data["conditions"]["total"] == 0 and len(data["daily"]) == 7
    assert data["setup"] == {
        "form_created": False,
        "channel_and_worker": False,
        "has_reports": False,
    }

    await sign_in(client, user.email, organization.id)
    mine = (await client.get(URL)).json()["data"]
    assert mine["kpis"]["reports_today"]["value"] == 1
    assert mine["timezone"] == "Asia/Jakarta"
    assert mine["setup"]["has_reports"] is True


async def test_needs_a_session_and_a_valid_range(
    client: AsyncClient, organization: Workspace, user: User
) -> None:
    assert (await client.get(URL)).status_code == 401
    await sign_in(client, user.email, organization.id)
    assert (await client.get(URL, params={"range": "1y"})).status_code == 422
