"""Report downloads (roadmap 5.4, dashboard.md "Ekspor").

A request only records what to export; a Taskiq job writes the file to private storage, and the
person who asked (or an admin) downloads it through the API for 7 days, each download logged.
Excel has one sheet per structure, CSV exactly one structure. PDF and anonymized farmer names
come later (11.2; a field role for people's names in Domain 2).
"""

import asyncio
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_storage
from app.core.time import now_utc
from app.modules.audit import service as audit
from app.modules.forms import service as forms
from app.modules.reports import exports, repository
from app.modules.reports.errors import (
    ExportExpired,
    ExportFormatUnavailable,
    ExportNotFound,
    ExportNotReady,
    InvalidExport,
    TooManyExports,
)
from app.modules.reports.models import ReportExport
from app.modules.reports.schemas import (
    ConditionFilter,
    CreateExportRequest,
    ExportSpan,
    ReportExportOut,
)
from app.modules.workspaces.service import ActiveMember

logger = logging.getLogger(__name__)

MAX_OPEN_EXPORTS = 3
MAX_EXPORT_ROWS = 50_000
MAX_RANGE_DAYS = 366
KEEP_FILES = timedelta(days=7)
_FAILED = "Berkas gagal dibuat. Coba unduh lagi."
_TOO_LARGE = "Lebih dari 50.000 laporan. Persempit rentang tanggal, wilayah, atau struktur data."


# --- Range -------------------------------------------------------------------------------------


def resolve_range(
    span: ExportSpan, start: date | None, end: date | None, tz: ZoneInfo, now: datetime
) -> tuple[datetime, datetime]:
    """[since, until) in the workspace's days: today, the last 7 or 30 days including today, or
    custom local dates (both inclusive, at most 366 days)."""
    today = now.astimezone(tz).date()
    if span == "custom":
        if start is None or end is None:
            raise InvalidExport("Isi tanggal mulai dan tanggal akhir.", field="range")
        if start > end:
            raise InvalidExport("Tanggal mulai harus sebelum tanggal akhir.", field="range")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise InvalidExport("Rentang paling lama 366 hari.", field="range")
        first, last = start, end
    else:
        days = {"today": 1, "7d": 7, "30d": 30}[span]
        first, last = today - timedelta(days=days - 1), today

    def midnight(d: date) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=tz)

    return midnight(first), midnight(last + timedelta(days=1))


def report_filter(
    since: datetime,
    until: datetime,
    form_id: uuid.UUID | None,
    region_ids: list[uuid.UUID],
    conditions: list[ConditionFilter],
) -> repository.ReportFilter:
    return repository.ReportFilter(
        since=since,
        until=until,
        form_id=form_id,
        region_ids=tuple(region_ids),
        conditions=tuple(conditions),
    )


async def count(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    span: ExportSpan,
    start: date | None,
    end: date | None,
    form_id: uuid.UUID | None,
    region_ids: list[uuid.UUID],
    conditions: list[ConditionFilter],
) -> int:
    """How many reports a download with these choices would hold (the dialog's summary)."""
    tz = await repository.get_timezone(db, workspace_id)
    since, until = resolve_range(span, start, end, tz, now_utc())
    f = report_filter(since, until, form_id, region_ids, conditions)
    return await repository.count_reports(db, workspace_id, f)


# --- Request -----------------------------------------------------------------------------------


def _check(body: CreateExportRequest) -> None:
    if body.format == "pdf":
        raise ExportFormatUnavailable(field="format")
    if body.anonymize_farmers:
        raise InvalidExport("Menyamarkan nama petani belum tersedia.", field="anonymize_farmers")
    if body.include.map:
        raise InvalidExport("Peta hanya tersedia untuk PDF.", field="include.map")
    if body.format == "csv":
        if body.include.photos:
            raise InvalidExport("Foto tidak bisa disertakan di CSV.", field="include.photos")
        if body.form_id is None:
            raise InvalidExport("Pilih satu struktur data untuk CSV.", field="form_id")


def _out(row: ReportExport) -> ReportExportOut:
    return ReportExportOut(
        id=row.id,
        status=row.status,  # type: ignore[arg-type]  # checked by the table
        format=row.params["format"],
        row_count=row.row_count,
        filename=row.filename,
        error=row.error,
        created_at=row.created_at,
        finished_at=row.finished_at,
        expires_at=row.expires_at,
    )


async def create_export(
    db: AsyncSession, member: ActiveMember, body: CreateExportRequest
) -> ReportExportOut:
    """Record the request (the caller queues the job after this commits)."""
    _check(body)
    workspace_id = member.workspace_id
    if body.form_id is not None:
        await forms.get_form(db, workspace_id, body.form_id)  # 404 for another workspace's
    tz = await repository.get_timezone(db, workspace_id)
    since, until = resolve_range(body.range.type, body.range.from_, body.range.to, tz, now_utc())
    if await repository.count_open_exports(db, workspace_id) >= MAX_OPEN_EXPORTS:
        raise TooManyExports()
    params = {
        **body.model_dump(mode="json", by_alias=True),
        "since": since.isoformat(),
        "until": until.isoformat(),
    }
    row = ReportExport(
        workspace_id=workspace_id,
        requested_by_user_id=member.member.user_id,
        params=params,
        status="queued",
    )
    db.add(row)
    await db.flush()
    await audit.record(
        db,
        workspace_id=workspace_id,
        actor_user_id=member.member.user_id,
        action="report.export_requested",
        target=str(row.id),
        details=params,
    )
    await db.commit()
    await db.refresh(row)
    return _out(row)


async def _visible(db: AsyncSession, member: ActiveMember, export_id: uuid.UUID) -> ReportExport:
    """The person who asked, or an admin; anyone else sees nothing (404, not 403)."""
    row = await repository.get_export(db, member.workspace_id, export_id)
    if row is None or (
        member.role != "admin" and row.requested_by_user_id != member.member.user_id
    ):
        raise ExportNotFound()
    return row


async def get_export(
    db: AsyncSession, member: ActiveMember, export_id: uuid.UUID
) -> ReportExportOut:
    return _out(await _visible(db, member, export_id))


@dataclass(frozen=True)
class DownloadFile:
    filename: str
    media_type: str
    content: bytes


async def download(db: AsyncSession, member: ActiveMember, export_id: uuid.UUID) -> DownloadFile:
    row = await _visible(db, member, export_id)
    if row.status == "expired":
        raise ExportExpired()
    if row.status != "done" or row.object_key is None or row.filename is None:
        raise ExportNotReady()
    content = await get_storage().get(row.object_key)
    await audit.record(
        db,
        workspace_id=member.workspace_id,
        actor_user_id=member.member.user_id,
        action="report.export_downloaded",
        target=str(row.id),
        details={"row_count": row.row_count, "format": row.params["format"]},
    )
    await db.commit()
    fmt: exports.ExportFormat = row.params["format"]
    return DownloadFile(row.filename, exports.MEDIA_TYPES[fmt], content)


# --- Job ---------------------------------------------------------------------------------------


async def run_export(db: AsyncSession, export_id: uuid.UUID) -> None:
    """Write the file. A second run of the same job (retry, duplicate) finds nothing queued."""
    row = await repository.claim_export(db, export_id)
    if row is None:
        return
    row.status = "running"
    await db.commit()
    try:
        await _write(db, row)
    except Exception:
        logger.exception("report export %s failed", export_id)
        await db.rollback()
        failed = await repository.get_export(db, row.workspace_id, export_id)
        if failed is not None:
            failed.status, failed.error = "failed", _FAILED
            failed.finished_at = now_utc()
            await db.commit()


async def _write(db: AsyncSession, row: ReportExport) -> None:
    p = row.params
    workspace_id = row.workspace_id
    f = report_filter(
        datetime.fromisoformat(p["since"]),
        datetime.fromisoformat(p["until"]),
        uuid.UUID(p["form_id"]) if p.get("form_id") else None,
        [uuid.UUID(r) for r in p.get("region_ids", [])],
        p.get("conditions", []),
    )
    rows = await repository.export_rows(db, workspace_id, f, MAX_EXPORT_ROWS)
    now = now_utc()
    if len(rows) > MAX_EXPORT_ROWS:
        row.status, row.error, row.finished_at = "failed", _TOO_LARGE, now
        await db.commit()
        return

    fmt: exports.ExportFormat = p["format"]
    gps, photos = bool(p["include"]["gps"]), bool(p["include"]["photos"])
    tz = await repository.get_timezone(db, workspace_id)

    by_form: dict[uuid.UUID, list[repository.ReportRow]] = defaultdict(list)
    names: dict[uuid.UUID, str] = {}
    for r in rows:
        by_form[r.report.form_id].append(r)
        names[r.report.form_id] = r.form_name
    if f.form_id is not None and f.form_id not in by_form:
        form = await forms.get_form(db, workspace_id, f.form_id)
        by_form[f.form_id], names[f.form_id] = [], form.name

    sheets: list[tuple[str, list[list[exports.Cell]]]] = []
    used: set[str] = set()
    for form_id in sorted(by_form, key=lambda k: names[k].lower()):
        form_rows = by_form[form_id]
        form = await forms.get_form(db, workspace_id, form_id)
        version_ids = {r.report.form_version_id for r in form_rows}
        if form.current_version_id is not None:
            version_ids.add(form.current_version_id)
        versions = [
            await forms.get_version_definition(db, workspace_id, v, published_only=False)
            for v in version_ids
        ]
        versions.sort(key=lambda v: v.version, reverse=True)
        fields = exports.report_columns([v.definition for v in versions], gps=gps)
        lines = [
            exports.ReportSheetRow(
                code=r.report.code,
                worker=r.worker_name,
                received_at=r.report.received_at.astimezone(tz),
                region=r.region_name,
                complete=r.report.complete,
                needs_review=r.report.needs_review,
                lat=r.report.latitude,
                lng=r.report.longitude,
                accuracy_m=r.report.accuracy_m,
                photo_count=r.photo_count,
                answers=r.report.answers,
            )
            for r in form_rows
        ]
        table = exports.report_table(fields, lines, gps=gps, photos=photos)
        sheets.append((exports.sheet_title(names[form_id], used), table))
    if not sheets:  # nothing in range and no structure chosen: headers only
        sheets.append(("Laporan", exports.report_table([], [], gps=gps, photos=photos)))

    if fmt == "csv":
        content = await asyncio.to_thread(exports.write, "csv", sheets[0][1])
    else:
        content = await asyncio.to_thread(exports.write_sheets, sheets)
    key = f"workspaces/{workspace_id}/exports/{row.id}.{fmt}"
    await get_storage().put(key, content, exports.MEDIA_TYPES[fmt])
    scope = names.get(f.form_id) if f.form_id else None
    row.status = "done"
    row.object_key = key
    row.filename = exports.report_filename(scope, now.astimezone(tz), fmt)
    row.row_count = len(rows)
    row.finished_at = now
    row.expires_at = now + KEEP_FILES
    await db.commit()


async def expire_files(db: AsyncSession, limit: int = 200) -> int:
    """Delete files older than 7 days; the row stays as history, marked `expired`."""
    done = 0
    for row in await repository.list_expired_exports(db, now_utc(), limit):
        if row.object_key:
            await get_storage().delete(row.object_key)
        row.status, row.object_key = "expired", None
        done += 1
    await db.commit()
    return done
