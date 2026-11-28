"""GET /reports/voice-export (roadmap 12.6): only verified voice reports of one structure, oldest
first, one column per field, CSV or Excel, logged in the audit trail, editors up, and the
workspace boundary."""

import csv
import io
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.reports import service
from app.modules.reports.models import Report
from app.modules.workspaces.models import Workspace
from tests.api.v1.reports.test_reports import NOON, URL, VOICE, Topic
from tests.conftest import add_member, sign_in

EXPORT = f"{URL}/voice-export"


async def _verified(admin: AsyncClient, db: AsyncSession, topic: Topic, **kw: Any) -> Report:
    report = await topic.report(db, voice=VOICE, **kw)
    assert (await admin.post(f"{URL}/{report.id}/verify")).status_code == 200
    return report


def _rows(body: bytes) -> list[list[str]]:
    assert body.startswith("﻿".encode())
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))


async def test_csv_has_only_verified_voice_reports_oldest_first(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    newer = await _verified(admin, db, topic, received_at=NOON)
    older = await _verified(admin, db, topic, received_at=NOON - timedelta(hours=1))
    await topic.report(db, voice=VOICE, received_at=NOON)  # not verified
    await topic.report(db, received_at=NOON)  # chat, not voice

    response = await admin.get(EXPORT, params={"form_id": str(topic.form.id)})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="voice-survei-tanaman-'
    )
    header, *rows = _rows(response.content)
    assert header == [
        "Nomor",
        "Analis",
        "Diterima",
        "Diverifikasi oleh",
        "Waktu verifikasi",
        "Lokasi lahan",
        "Nama petani",
        "Luas lahan (ha)",
        "Kondisi tanaman",
    ]
    assert [r[0] for r in rows] == [older.code, newer.code]
    # Workspace time (Asia/Jakarta, UTC+7), plain numbers, choice labels; photos left out.
    assert rows[1][1:3] == ["Budi", "2026-11-18 12:00"]
    assert rows[1][3] == "Dina Admin" and rows[1][4]
    assert rows[1][5:] == ["-6.82, 107.14", "Pak Slamet", "1.5", "Terserang"]

    log = await db.scalar(select(AuditLog).where(AuditLog.action == "report.voice_exported"))
    assert log is not None and log.target == str(topic.form.id)
    assert log.details["row_count"] == 2 and log.details["format"] == "csv"


async def test_range_filters_by_time_received(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    await _verified(admin, db, topic, received_at=NOON - timedelta(days=2))
    kept = await _verified(admin, db, topic, received_at=NOON)
    since = (NOON - timedelta(days=1)).isoformat()
    response = await admin.get(EXPORT, params={"form_id": str(topic.form.id), "since": since})
    assert [r[0] for r in _rows(response.content)[1:]] == [kept.code]


async def test_excel_keeps_numbers_as_numbers(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    report = await _verified(admin, db, topic, received_at=NOON)
    response = await admin.get(EXPORT, params={"form_id": str(topic.form.id), "format": "xlsx"})
    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith('.xlsx"')
    sheet = load_workbook(io.BytesIO(response.content)).active
    assert sheet is not None
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0][7] == "Luas lahan (ha)"
    assert rows[1][0] == report.code and rows[1][7] == 1.5


async def test_empty_export_still_has_the_columns(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    # Columns come from the published version when no report is there yet.
    topic.form.current_version_id = topic.version.id
    await db.flush()
    response = await admin.get(EXPORT, params={"form_id": str(topic.form.id)})
    assert response.status_code == 200
    assert _rows(response.content) == [_rows(response.content)[0]]
    assert "Nama petani" in _rows(response.content)[0]


async def test_too_many_rows_is_refused(
    admin: AsyncClient, db: AsyncSession, topic: Topic, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "MAX_VOICE_EXPORT_ROWS", 1)
    await _verified(admin, db, topic, received_at=NOON)
    await _verified(admin, db, topic, received_at=NOON)
    response = await admin.get(EXPORT, params={"form_id": str(topic.form.id)})
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "export_too_large"


async def test_reviewers_and_other_workspaces_cannot_export(
    client: AsyncClient, db: AsyncSession, organization: Workspace, topic: Topic
) -> None:
    params = {"form_id": str(topic.form.id)}
    assert (await client.get(EXPORT, params=params)).status_code == 401
    await add_member(db, organization.id, email="rani@contoh.id", role="reviewer")
    await sign_in(client, "rani@contoh.id", organization.id)
    forbidden = await client.get(EXPORT, params=params)
    assert forbidden.status_code == 403 and forbidden.json()["errors"][0]["code"] == "forbidden"

    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    await add_member(db, other.id, email="x@contoh.id", role="admin")
    await sign_in(client, "x@contoh.id", other.id)
    missing = await client.get(EXPORT, params=params)
    assert missing.status_code == 404 and missing.json()["errors"][0]["code"] == "form_not_found"
