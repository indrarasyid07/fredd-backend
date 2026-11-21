"""Supervisor corrections and verification (roadmap 12.5): a corrected value is read like a spoken
one, the report's filter columns and dashboard values follow it, every change keeps its reason in
the history and the audit trail, and a verified report is no longer changed."""

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.reports.models import Report, ReportValue
from app.modules.workspaces.models import Workspace
from tests.api.v1.reports.test_reports import URL, Topic
from tests.conftest import add_member, sign_in


async def _correct(  # noqa: ANN202
    client: AsyncClient, report: Report, key: str, value: str, reason: str = "Salah dengar"
):
    return await client.post(
        f"{URL}/{report.id}/corrections", json={"field_key": key, "value": value, "reason": reason}
    )


async def test_correction_updates_the_report_and_keeps_history(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    report = await topic.report(db)
    response = await _correct(admin, report, "land_area", "2,5 hektar", "Analis menyebut 2,5")
    assert response.status_code == 200
    data = response.json()["data"]
    assert next(f for f in data["fields"] if f["key"] == "land_area")["display"] == "2,5 ha"
    assert data["area_ha"] == 2.5
    (correction,) = data["corrections"]
    assert (correction["label"], correction["old_display"], correction["new_display"]) == (
        "Luas lahan",
        "1,5 ha",
        "2,5 ha",
    )
    assert (correction["reason"], correction["by"]) == ("Analis menyebut 2,5", "Dina Admin")

    await db.refresh(report)
    assert report.answers["land_area"] == "2.5" and report.area_ha == Decimal("2.5")
    numbers = await db.scalars(
        select(ReportValue.number).where(
            ReportValue.report_id == report.id, ReportValue.field_key == "land_area"
        )
    )
    assert list(numbers) == [Decimal("2.5")]
    log = await db.scalar(select(AuditLog).where(AuditLog.action == "report.corrected"))
    assert log is not None and log.details["reason"] == "Analis menyebut 2,5"


async def test_correcting_the_condition_moves_the_filter_column(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    report = await topic.report(db)
    assert (await _correct(admin, report, "condition", "sehat")).status_code == 200
    await db.refresh(report)
    assert report.condition == "healthy"


async def test_unreadable_or_unknown_corrections_are_refused(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    report = await topic.report(db)
    bad = await _correct(admin, report, "land_area", "banyak")
    assert bad.status_code == 422 and bad.json()["errors"][0]["code"] == "invalid_correction"
    wrong_unit = await _correct(admin, report, "land_area", "3 kg")
    assert wrong_unit.json()["errors"][0]["code"] == "invalid_correction"
    assert "ha" in wrong_unit.json()["message"]
    for key in ("location", "photos", "nope"):
        refused = await _correct(admin, report, key, "x")
        assert refused.json()["errors"][0]["code"] == "field_not_correctable"
    no_reason = await _correct(admin, report, "land_area", "2", reason="")
    assert no_reason.status_code == 422
    await db.refresh(report)
    assert report.answers["land_area"] == "1.5"


async def test_verification_locks_the_report(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    report = await topic.report(db)
    other = await topic.report(db)
    verified = await admin.post(f"{URL}/{report.id}/verify")
    assert verified.status_code == 200
    state = verified.json()["data"]["verification"]
    assert state["verified"] is True and state["verified_by"] == "Dina Admin"
    again = await admin.post(f"{URL}/{report.id}/verify")
    assert (
        again.status_code == 409 and again.json()["errors"][0]["code"] == "report_already_verified"
    )
    assert (await _correct(admin, report, "land_area", "2")).status_code == 409
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "report.verified"))

    async def ids(**params: str) -> set[str]:
        return {r["id"] for r in (await admin.get(URL, params=params)).json()["data"]}

    assert await ids(verified="true") == {str(report.id)}
    assert await ids(verified="false") == {str(other.id)}


async def test_other_workspaces_cannot_correct_or_verify(
    client: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    report = await topic.report(db)
    other = Workspace(name="Lab Lain", type="organization")
    db.add(other)
    await db.flush()
    await add_member(db, other.id, email="x@contoh.id", role="admin")
    await sign_in(client, "x@contoh.id", other.id)
    assert (await client.post(f"{URL}/{report.id}/verify")).status_code == 404
    assert (await _correct(client, report, "land_area", "2")).status_code == 404
