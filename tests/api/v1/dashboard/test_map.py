"""The dashboard map (roadmap 5.2) and per-structure headline numbers (11.3a): regencies with the
alert colour or the most common answer, located points, the 2.000 cap, health privacy, simplified
outlines, and the workspace boundary."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.dashboard import map as report_map
from app.modules.dashboard import service
from app.modules.reference_data import service as reference_data
from app.modules.reference_data.models import ReferenceData
from app.modules.workspaces.models import Workspace
from tests.api.v1.dashboard.test_summary import EAST, NOW, WEST, jakarta
from tests.api.v1.reference_data.test_reference_data import FEATURES
from tests.api.v1.reports.test_reports import ANSWERS, Topic, _topic
from tests.conftest import add_member, sign_in

MAP = "/api/v1/dashboard/map"


@pytest.fixture(autouse=True)
def _now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(report_map, "now_utc", lambda: NOW)


@pytest.fixture
async def admin(client: AsyncClient, organization: Workspace, user: User) -> AsyncClient:
    return await sign_in(client, user.email, organization.id)


@pytest.fixture
async def topic(db: AsyncSession, organization: Workspace) -> Topic:
    await reference_data.seed_platform_regions(db, FEATURES)
    t = await _topic(db, organization)
    t.form.current_version_id, t.version.published_at = t.version.id, NOW
    await db.flush()
    return t


async def _report(
    db: AsyncSession, topic: Topic, location: dict[str, Any] | None, **kw: Any
) -> Any:
    answers = {**ANSWERS, "location": location, **kw}
    return await topic.report(db, answers, received_at=jakarta(18, 9))


async def _regency(db: AsyncSession, code: str) -> ReferenceData:
    row = await db.scalar(select(ReferenceData).where(ReferenceData.code == code))
    assert row is not None
    return row


async def test_regions_take_the_alert_colour_and_points_are_located(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    # Kabupaten Barat: 1 of 3 infected (33% ≥ 25%) → infected; Timur: healthy only.
    await _report(db, topic, WEST, condition="infected")
    await _report(db, topic, WEST, condition="healthy")
    await _report(db, topic, {**WEST, "accuracy_m": 120}, condition="healthy")
    await _report(db, topic, EAST, condition="healthy")
    await _report(db, topic, None, condition="attention")  # no point, no region

    data = (await admin.get(MAP)).json()["data"]
    assert (data["total"], data["located"], data["privacy"]) == (5, 4, "full")
    barat = await _regency(db, "99.01")
    regions = {r["name"]: r for r in data["regions"]}
    west = regions["Kabupaten Barat"]
    assert west["region_id"] == str(barat.id)  # the district's report counts for its regency
    assert (west["count"], west["color"]) == (3, "infected")
    assert west["by_value"] == {"infected": 1, "healthy": 2}
    assert west["centroid"] is not None and west["latest_report_id"]
    assert regions["Kabupaten Timur"]["color"] == "healthy"
    assert len(data["points"]) == 4
    assert sorted(p["approximate"] for p in data["points"]) == [False, False, False, True]
    legend = {v["value"]: v["count"] for v in data["color_field"]["values"]}
    assert legend == {"healthy": 3, "attention": 1, "infected": 1}
    assert data["color_field"]["kind"] == "condition"


async def test_value_filter_and_point_cap(
    admin: AsyncClient, db: AsyncSession, topic: Topic, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report_map, "MAX_POINTS", 1)
    await _report(db, topic, WEST, condition="infected")
    await _report(db, topic, EAST, condition="infected")
    await _report(db, topic, EAST, condition="healthy")
    data = (await admin.get(MAP, params={"value": "infected"})).json()["data"]
    assert data["total"] == 2 and data["truncated"] is True and len(data["points"]) == 1
    # The legend still counts every value.
    assert {v["value"]: v["count"] for v in data["color_field"]["values"]}["healthy"] == 1


async def test_a_structure_is_coloured_by_its_choice_field(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    await _report(db, topic, WEST, condition="infected")
    params = {"form_id": str(topic.form.id), "color_by": "condition"}
    data = (await admin.get(MAP, params=params)).json()["data"]
    assert data["color_field"]["label"] == "Kondisi tanaman"
    assert data["regions"][0]["color"] == "infected"


async def test_health_structures_send_regions_only(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    topic.form.settings = {"sector_code": "health"}
    await db.flush()
    for _ in range(5):
        await _report(db, topic, WEST)
    await _report(db, topic, EAST)  # one report: left out
    data = (await admin.get(MAP, params={"form_id": str(topic.form.id)})).json()["data"]
    assert data["privacy"] == "regions_only" and data["points"] == []
    assert [r["name"] for r in data["regions"]] == ["Kabupaten Barat"]
    assert data["hidden_regions"] == 1 and data["regions"][0]["latest_report_id"] is None


async def test_boundaries_are_simplified_geojson(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    barat = await _regency(db, "99.01")
    response = await admin.get("/api/v1/dashboard/boundaries", params={"id": str(barat.id)})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=86400"
    data = response.json()["data"]
    assert data["type"] == "FeatureCollection"
    (feature,) = data["features"]
    assert feature["id"] == str(barat.id) and feature["properties"]["name"] == "Kabupaten Barat"
    assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")


async def test_form_dashboard_has_sector_and_headline_numbers(
    db: AsyncSession, topic: Topic
) -> None:
    topic.form.settings = {"sector_code": "agriculture", "template_code": "00"}
    await db.flush()
    await topic.report(db, received_at=jakarta(18, 8))
    await topic.report(db, {**ANSWERS, "farmer_name": None}, received_at=jakarta(18, 9))
    await topic.report(db, received_at=jakarta(17, 8))  # yesterday before 10:30
    out = await service.form_dashboard(db, topic.workspace.id, topic.form.id, now=NOW)
    assert (out.form.sector_code, out.form.template_code, out.form.has_location) == (
        "agriculture",
        "00",
        True,
    )
    assert out.kpis is not None
    assert (out.total, out.kpis.previous_total, out.kpis.delta_pct) == (2, 1, 100.0)
    assert (out.kpis.workers_reporting, out.kpis.complete_percent) == (1, 50)


async def test_other_workspace_sees_nothing(
    client: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    await _report(db, topic, WEST)
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    await add_member(db, other.id, email="rani@contoh.id", role="reviewer")
    await sign_in(client, "rani@contoh.id", other.id)
    data = (await client.get(MAP)).json()["data"]
    assert (data["total"], data["regions"], data["points"]) == (0, [], [])
    missing = await client.get(MAP, params={"form_id": str(topic.form.id)})
    assert missing.status_code == 404
