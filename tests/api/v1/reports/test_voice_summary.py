"""GET /reports/voice-summary (roadmap 12.4): voice reports counted by day, channel, month and
verification in the workspace time zone, the mean speech confidence of the last 7 days, the most
corrected field of the last 30 days, one analyst at a time, and the workspace boundary."""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extension_workers.models import ExtensionWorker
from app.modules.reports import service
from app.modules.workspaces.models import Workspace
from tests.api.v1.reports.test_reports import DEFINITION, NOON, URL, VOICE, Topic
from tests.conftest import add_member, sign_in

SUMMARY = f"{URL}/voice-summary"


@pytest.fixture(autouse=True)
def _now(monkeypatch: pytest.MonkeyPatch) -> None:
    # 12:00 in Asia/Jakarta on 18 November 2026.
    monkeypatch.setattr(service, "now_utc", lambda: NOON)


async def test_empty_workspace_has_zeros_and_no_rates(admin: AsyncClient) -> None:
    body = (await admin.get(SUMMARY)).json()
    assert body["success"]
    assert body["data"] == {
        "total": 0,
        "pending": 0,
        "verified": 0,
        "today": 0,
        "yesterday": 0,
        "today_telegram": 0,
        "today_whatsapp": 0,
        "this_month": 0,
        "last_month": 0,
        "confidence_7d": None,
        "corrected_share_30d": None,
        "most_corrected": None,
    }


async def test_counts_follow_the_workspace_day_and_channel(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    on_whatsapp = ExtensionWorker(
        workspace_id=topic.workspace.id, name="Sari", phone_e164="+6281100001234"
    )
    db.add(on_whatsapp)
    await db.flush()
    # 00:30 Jakarta today is still yesterday in UTC.
    early = await topic.report(db, voice=VOICE, received_at=NOON - timedelta(hours=11, minutes=30))
    await topic.report(db, voice=VOICE, received_at=NOON)
    await service.create_report(
        db,
        workspace_id=topic.workspace.id,
        form_id=topic.form.id,
        form_version_id=topic.version.id,
        definition=DEFINITION,
        extension_worker_id=on_whatsapp.id,
        conversation_id=None,
        answers={"farmer_name": "Bu Ani"},
        voice=VOICE,
        received_at=NOON,
    )
    await topic.report(db, voice=VOICE, received_at=NOON - timedelta(days=1))  # yesterday
    await topic.report(db, voice=VOICE, received_at=NOON - timedelta(days=30))  # October
    await topic.report(db, received_at=NOON)  # chat, not voice
    assert (await admin.post(f"{URL}/{early.id}/verify")).status_code == 200

    data = (await admin.get(SUMMARY)).json()["data"]
    assert (data["total"], data["pending"], data["verified"]) == (5, 4, 1)
    assert (data["today"], data["yesterday"]) == (3, 1)
    assert (data["today_telegram"], data["today_whatsapp"]) == (2, 1)
    assert (data["this_month"], data["last_month"]) == (4, 1)

    mine = (await admin.get(SUMMARY, params={"extension_worker_id": str(on_whatsapp.id)})).json()
    assert (mine["data"]["total"], mine["data"]["today_whatsapp"]) == (1, 1)


async def test_confidence_and_corrections(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    fixed = await topic.report(db, voice=VOICE, received_at=NOON)
    await topic.report(db, voice=VOICE, received_at=NOON - timedelta(days=1))
    # Older than 7 days: out of the confidence, still in the 30-day corrections.
    await topic.report(
        db,
        voice={**VOICE, "confidence": {"farmer_name": 0.1}},
        received_at=NOON - timedelta(days=10),
    )
    response = await admin.post(
        f"{URL}/{fixed.id}/corrections",
        json={"field_key": "land_area", "value": "2,5", "reason": "Analis menyebut 2,5"},
    )
    assert response.status_code == 200

    data = (await admin.get(SUMMARY)).json()["data"]
    assert data["confidence_7d"] == pytest.approx(0.625)  # (0.75 + 0.5) / 2
    assert data["corrected_share_30d"] == pytest.approx(1 / 3)
    assert data["most_corrected"] == "Luas lahan"


async def test_other_workspace_and_strangers(
    client: AsyncClient, db: AsyncSession, topic: Topic, organization: Workspace
) -> None:
    await topic.report(db, voice=VOICE, received_at=NOON)
    other = Workspace(name="Lain", type="organization")
    db.add(other)
    await db.flush()
    await add_member(db, other.id, email="x@contoh.id", role="admin")
    await sign_in(client, "x@contoh.id", other.id)
    assert (await client.get(SUMMARY)).json()["data"]["total"] == 0
    await sign_in(client, "x@contoh.id", organization.id)
    assert (await client.get(SUMMARY)).status_code in (403, 404)
