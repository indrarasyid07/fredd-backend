"""GET /dashboard/field-workers (Pantauan Lapangan, roadmap 5.2): each active worker's newest
report in the range, tone and list group, headline numbers, health privacy, and the workspace
boundary."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.dashboard import map as report_map
from app.modules.extension_workers.models import ExtensionWorker
from app.modules.reference_data import service as reference_data
from app.modules.workspaces.models import Workspace
from tests.api.v1.dashboard.test_summary import EAST, NOW, WEST, jakarta
from tests.api.v1.reference_data.test_reference_data import FEATURES
from tests.api.v1.reports.test_reports import ANSWERS, Topic, _topic
from tests.conftest import add_member, sign_in

URL = "/api/v1/dashboard/field-workers"


@pytest.fixture(autouse=True)
def _now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(report_map, "now_utc", lambda: NOW)


@pytest.fixture
async def admin(client: AsyncClient, organization: Workspace, user: User) -> AsyncClient:
    return await sign_in(client, user.email, organization.id)


@pytest.fixture
async def topic(db: AsyncSession, organization: Workspace) -> Topic:
    await reference_data.seed_platform_regions(db, FEATURES)
    return await _topic(db, organization)


async def _report(db: AsyncSession, topic: Topic, worker: Any, at: Any, **answers: Any) -> Any:
    topic.worker = worker
    return await topic.report(db, {**ANSWERS, **answers}, received_at=at)


async def _worker(db: AsyncSession, topic: Topic, name: str, **kw: Any) -> ExtensionWorker:
    w = ExtensionWorker(workspace_id=topic.workspace.id, name=name, **kw)
    db.add(w)
    await db.flush()
    return w


async def test_workers_tone_group_and_numbers(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    budi = topic.worker
    sari = await _worker(db, topic, "Sari", phone_e164="+6281100001234")
    await _worker(db, topic, "Yusuf", telegram_user_id="77")  # nothing today
    await _report(db, topic, budi, jakarta(18, 7), location=WEST, condition="healthy")
    newest = await _report(db, topic, budi, jakarta(18, 9), location=WEST, condition="infected")
    await _report(db, topic, sari, jakarta(18, 8), location=EAST, condition="healthy")
    await _report(db, topic, sari, jakarta(17, 8), location=EAST)  # yesterday, same time

    data = (await admin.get(URL)).json()["data"]
    by_name = {w["name"]: w for w in data["workers"]}
    assert [w["name"] for w in data["workers"]][:2] == ["Budi", "Sari"]  # newest first
    b = by_name["Budi"]
    assert (b["tone"], b["group"], b["reports"], b["channel"]) == (
        "infected",
        "needs",
        2,
        "telegram",
    )
    assert b["latest"]["report_id"] == str(newest.id) and b["latest"]["lat"] == WEST["lat"]
    assert b["latest"]["region"] == "Kecamatan Utara"
    assert (by_name["Sari"]["tone"], by_name["Sari"]["group"]) == ("healthy", "active")
    assert (by_name["Yusuf"]["tone"], by_name["Yusuf"]["latest"]) == ("inactive", None)
    assert data["counts"] == {"all": 3, "active": 1, "needs": 1, "inactive": 1}
    assert data["legend"] == {"healthy": 1, "attention": 0, "infected": 1, "inactive": 1}
    k = data["kpis"]
    assert (k["workers_active"], k["workers_total"], k["workers_active_before"]) == (2, 3, 1)
    assert (k["reports"], k["reports_delta_pct"]) == (3, 200.0)
    assert (k["cases"], k["infected"], k["districts"], k["regencies"]) == (1, 1, 1, 2)
    assert k["whatsapp_pct"] + k["telegram_pct"] == 100


async def test_health_reports_give_no_point(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    topic.form.settings = {"sector_code": "health"}
    await db.flush()
    await _report(db, topic, topic.worker, jakarta(18, 9), location=WEST, condition="healthy")
    (worker,) = (await admin.get(URL)).json()["data"]["workers"]
    assert worker["latest"]["lat"] is None and worker["latest"]["lng"] is None
    assert worker["group"] == "active"


async def test_other_workspace_sees_nothing(
    client: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    await _report(db, topic, topic.worker, jakarta(18, 9), location=WEST)
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    await add_member(db, other.id, email="rani@contoh.id", role="reviewer")
    await sign_in(client, "rani@contoh.id", other.id)
    data = (await client.get(URL)).json()["data"]
    assert data["workers"] == [] and data["kpis"]["reports"] == 0
