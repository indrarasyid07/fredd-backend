"""Report downloads (roadmap 5.4–5.5): GET /reports/count, POST /reports/exports, the job that
writes the file, status and download for the person who asked or an admin, checks on the
choices, the 3-at-once limit, expiry after 7 days, the audit trail, and the workspace boundary."""

import csv
import io
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session as db_session
from app.modules.audit.models import AuditLog
from app.modules.reference_data.models import ReferenceData
from app.modules.reports import report_exports
from app.modules.reports.models import ReportExport
from app.modules.workspaces.models import Workspace
from tests.api.v1.reports.test_reports import ANSWERS, NOON, URL, Topic
from tests.conftest import MemoryStorage, add_member, sign_in

EXPORTS = f"{URL}/exports"


@pytest.fixture(autouse=True)
def _now_and_session(monkeypatch: pytest.MonkeyPatch, db: AsyncSession) -> None:
    # 12:00 in Asia/Jakarta on 18 November 2026; the inline job uses the test's session.
    monkeypatch.setattr(report_exports, "now_utc", lambda: NOON)

    @asynccontextmanager
    async def test_session() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr(db_session, "open_session", test_session)


def _body(**kw: Any) -> dict[str, Any]:
    return {"format": "xlsx", "range": {"type": "7d"}, **kw}


async def _done(admin: AsyncClient, **kw: Any) -> dict[str, Any]:
    response = await admin.post(EXPORTS, json=_body(**kw))
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "done", data
    return data


async def test_count_follows_range_and_filters(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    await topic.report(db, received_at=NOON)
    await topic.report(
        db, {**ANSWERS, "condition": "healthy"}, received_at=NOON - timedelta(days=3)
    )
    await topic.report(db, received_at=NOON - timedelta(days=20))

    async def n(**params: Any) -> int:
        response = await admin.get(f"{URL}/count", params=params)
        assert response.status_code == 200, response.text
        return response.json()["data"]["count"]

    assert await n(range="today") == 1
    assert await n(range="7d") == 2
    assert await n(range="30d") == 3
    assert await n(range="30d", condition="healthy") == 1
    assert await n(range="custom", **{"from": "2026-10-29", "to": "2026-11-15"}) == 2
    bad = await admin.get(f"{URL}/count", params={"range": "custom", "from": "2026-11-15"})
    assert bad.status_code == 422 and bad.json()["errors"][0]["code"] == "invalid_export"


async def test_a_regency_covers_its_districts(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    regency = ReferenceData(type="region", code="99.01", value="Kabupaten Uji", level="regency")
    db.add(regency)
    await db.flush()
    district = ReferenceData(
        type="region",
        code="99.01.01",
        value="Kecamatan Uji",
        level="district",
        parent_id=regency.id,
    )
    db.add(district)
    await db.flush()
    for region in (regency, district, None):
        report = await topic.report(db, received_at=NOON)
        report.region_id = region.id if region else None
    await db.flush()
    response = await admin.get(
        f"{URL}/count", params={"range": "today", "region_id": str(regency.id)}
    )
    assert response.json()["data"]["count"] == 2


async def test_excel_has_one_sheet_per_structure(
    admin: AsyncClient, db: AsyncSession, topic: Topic, media_store: MemoryStorage
) -> None:
    older = await topic.report(db, received_at=NOON - timedelta(hours=2))
    newer = await topic.report(db, received_at=NOON)
    await topic.report(db, received_at=NOON - timedelta(days=9))  # outside 7 days

    data = await _done(admin, include={"photos": True, "gps": True})
    assert data["row_count"] == 2 and data["format"] == "xlsx"
    assert data["filename"] == "laporan-semua-20261118.xlsx"
    assert data["expires_at"] == (NOON + timedelta(days=7)).isoformat().replace("+00:00", "Z")

    response = await admin.get(f"{EXPORTS}/{data['id']}/download")
    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith('"laporan-semua-20261118.xlsx"')
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == ["Survei Tanaman"]
    rows = list(book.active.iter_rows(values_only=True))  # type: ignore[union-attr]
    head = rows[0]
    assert head[:6] == ("Nomor", "Penyuluh", "Diterima", "Wilayah", "Lengkap", "Perlu ditinjau")
    assert head[6:10] == ("Lintang", "Bujur", "Akurasi GPS (m)", "Jumlah foto")
    assert "Luas lahan (ha)" in head and "Foto lahan" not in head
    assert [r[0] for r in rows[1:]] == [older.code, newer.code]
    assert rows[1][1] == "Budi" and rows[1][6] == -6.82 and rows[1][9] == 2
    assert rows[1][head.index("Luas lahan (ha)")] == 1.5

    actions = set(await db.scalars(select(AuditLog.action)))
    assert {"report.export_requested", "report.export_downloaded"} <= actions
    assert len(media_store.objects) == 1


async def test_csv_is_one_structure_without_gps(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    report = await topic.report(db, received_at=NOON)
    data = await _done(
        admin, format="csv", form_id=str(topic.form.id), include={"gps": False, "photos": False}
    )
    assert data["filename"] == "laporan-survei-tanaman-20261118.csv"
    body = (await admin.get(f"{EXPORTS}/{data['id']}/download")).content
    head, row = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
    assert "Lintang" not in head and "Lokasi lahan" not in head
    assert row[0] == report.code and row[2] == "2026-11-18 12:00"


async def test_empty_download_still_has_columns(admin: AsyncClient, topic: Topic) -> None:
    topic.form.current_version_id = topic.version.id
    data = await _done(admin, format="csv", form_id=str(topic.form.id))
    assert data["row_count"] == 0


@pytest.mark.parametrize(
    ("body", "code", "field"),
    [
        ({"format": "pdf"}, "export_format_unavailable", "format"),
        ({"format": "csv"}, "invalid_export", "form_id"),
        ({"format": "csv", "include": {"photos": True}}, "invalid_export", "include.photos"),
        ({"include": {"map": True}}, "invalid_export", "include.map"),
        ({"anonymize_farmers": True}, "invalid_export", "anonymize_farmers"),
        (
            {"range": {"type": "custom", "from": "2026-11-10", "to": "2026-11-01"}},
            "invalid_export",
            "range",
        ),
        (
            {"range": {"type": "custom", "from": "2025-01-01", "to": "2026-11-01"}},
            "invalid_export",
            "range",
        ),
    ],
)
async def test_choices_are_checked(
    admin: AsyncClient, topic: Topic, body: dict[str, Any], code: str, field: str
) -> None:
    payload = _body(**body)
    if body.get("format") == "csv" and "include" in body:
        payload["form_id"] = str(topic.form.id)
    response = await admin.post(EXPORTS, json=payload)
    assert response.status_code == 422
    error = response.json()["errors"][0]
    assert (error["code"], error["field"]) == (code, field)


async def test_three_open_exports_at_most(
    admin: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    for _ in range(3):
        db.add(
            ReportExport(workspace_id=organization.id, params={"format": "xlsx"}, status="running")
        )
    await db.flush()
    response = await admin.post(EXPORTS, json=_body())
    assert response.status_code == 429
    assert response.json()["errors"][0]["code"] == "too_many_exports"


async def test_too_many_rows_fail_with_a_reason(
    admin: AsyncClient, db: AsyncSession, topic: Topic, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report_exports, "MAX_EXPORT_ROWS", 1)
    await topic.report(db, received_at=NOON)
    await topic.report(db, received_at=NOON)
    data = (await admin.post(EXPORTS, json=_body())).json()["data"]
    assert data["status"] == "failed" and "50.000" in data["error"]
    response = await admin.get(f"{EXPORTS}/{data['id']}/download")
    assert (
        response.status_code == 409 and response.json()["errors"][0]["code"] == "export_not_ready"
    )


async def test_files_expire_after_seven_days(
    admin: AsyncClient,
    db: AsyncSession,
    topic: Topic,
    media_store: MemoryStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = await _done(admin)
    monkeypatch.setattr(report_exports, "now_utc", lambda: NOON + timedelta(days=8))
    assert await report_exports.expire_files(db) == 1
    assert media_store.objects == {}
    response = await admin.get(f"{EXPORTS}/{data['id']}/download")
    assert response.status_code == 410 and response.json()["errors"][0]["code"] == "export_expired"
    status = (await admin.get(f"{EXPORTS}/{data['id']}")).json()["data"]["status"]
    assert status == "expired"


async def test_who_may_see_an_export(
    client: AsyncClient, admin: AsyncClient, db: AsyncSession, topic: Topic, organization: Workspace
) -> None:
    data = await _done(admin)
    # Another editor of the same workspace: not theirs, not an admin.
    await add_member(db, organization.id, email="editor@contoh.id", role="form_editor")
    await sign_in(client, "editor@contoh.id", organization.id)
    assert (await client.get(f"{EXPORTS}/{data['id']}")).status_code == 404
    # A reviewer cannot start one.
    await add_member(db, organization.id, email="rev@contoh.id", role="reviewer")
    await sign_in(client, "rev@contoh.id", organization.id)
    assert (await client.post(EXPORTS, json=_body())).status_code == 403
    # Another workspace's admin sees nothing.
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    await add_member(db, other.id, email="lain@contoh.id", role="admin")
    await sign_in(client, "lain@contoh.id", other.id)
    assert (await client.get(f"{EXPORTS}/{data['id']}")).status_code == 404
    assert (await client.get(f"{EXPORTS}/{data['id']}/download")).status_code == 404
    other_form = await client.post(EXPORTS, json=_body(form_id=str(topic.form.id)))
    assert other_form.status_code == 404
