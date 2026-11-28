import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Select, and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

# Read-only joins for the names shown next to a report.
from app.modules.auth.models import User
from app.modules.extension_workers.models import ExtensionWorker
from app.modules.forms.models import Form
from app.modules.reference_data.models import ReferenceData
from app.modules.reports.models import (
    Report,
    ReportCodeCounter,
    ReportCorrection,
    ReportPhoto,
    ReportValue,
)
from app.modules.workspaces.models import Workspace


async def get_timezone(db: AsyncSession, workspace_id: uuid.UUID) -> ZoneInfo:
    name = await db.scalar(select(Workspace.timezone).where(Workspace.id == workspace_id))
    return ZoneInfo(name or "Asia/Jakarta")


async def take_code_number(db: AsyncSession, workspace_id: uuid.UUID, period: str) -> int:
    """The next number for this workspace and month, atomically (row lock on the counter)."""
    result = await db.execute(
        insert(ReportCodeCounter)
        .values(workspace_id=workspace_id, period=period, last_value=1)
        .on_conflict_do_update(
            index_elements=["workspace_id", "period"],
            set_={"last_value": ReportCodeCounter.last_value + 1},
        )
        .returning(ReportCodeCounter.last_value)
    )
    return int(result.scalar_one())


async def get_report(
    db: AsyncSession, workspace_id: uuid.UUID, report_id: uuid.UUID
) -> Report | None:
    return await db.scalar(
        select(Report).where(Report.workspace_id == workspace_id, Report.id == report_id)
    )


@dataclass(frozen=True)
class ReportRow:
    """A report with the names a list shows next to it."""

    report: Report
    worker_name: str
    telegram_user_id: str | None
    form_name: str
    region_name: str | None
    photo_count: int


def _rows_query() -> Select[Report, str, str | None, str, str, int]:
    photos = (
        select(func.count(ReportPhoto.id))
        .where(ReportPhoto.report_id == Report.id)
        .correlate(Report)
        .scalar_subquery()
    )
    region = aliased(ReferenceData)
    return (
        select(
            Report,
            ExtensionWorker.name,
            ExtensionWorker.telegram_user_id,
            Form.name,
            region.value,
            photos,
        )
        .join(ExtensionWorker, ExtensionWorker.id == Report.extension_worker_id)
        .join(Form, Form.id == Report.form_id)
        .outerjoin(region, region.id == Report.region_id)
    )


def _matches(q: str) -> ColumnElement[bool]:
    """Code, extension worker or region name contains `q` (case-insensitive, `%`/`_` literal)."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    regions = select(ReferenceData.id).where(ReferenceData.value.ilike(pattern, escape="\\"))
    return or_(
        Report.code.ilike(pattern, escape="\\"),
        ExtensionWorker.name.ilike(pattern, escape="\\"),
        Report.region_id.in_(regions),
    )


def _row(values: Any) -> ReportRow:
    report, worker_name, telegram_user_id, form_name, region_name, photo_count = values
    return ReportRow(report, worker_name, telegram_user_id, form_name, region_name, photo_count)


async def list_reports(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    form_id: uuid.UUID | None,
    extension_worker_id: uuid.UUID | None,
    region_id: uuid.UUID | None,
    conditions: list[str] | None,
    needs_review: bool | None,
    verified: bool | None,
    voice: bool | None,
    since: datetime | None,
    until: datetime | None,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
    q: str | None = None,
) -> list[ReportRow]:
    """Newest first. One extra row tells the caller there is a next page; `after` is the
    (received_at, id) of the previous page's last row."""
    stmt = _rows_query().where(Report.workspace_id == workspace_id)
    if form_id is not None:
        stmt = stmt.where(Report.form_id == form_id)
    if extension_worker_id is not None:
        stmt = stmt.where(Report.extension_worker_id == extension_worker_id)
    if region_id is not None:
        stmt = stmt.where(Report.region_id == region_id)
    if conditions:
        known = [c for c in conditions if c != "unknown"]
        clauses = [Report.condition.in_(known)] if known else []
        if "unknown" in conditions:
            clauses.append(Report.condition.is_(None))
        stmt = stmt.where(or_(*clauses))
    if needs_review is not None:
        stmt = stmt.where(Report.needs_review.is_(needs_review))
    if verified is not None:
        is_verified = Report.verified_at.is_not(None)
        stmt = stmt.where(is_verified if verified else ~is_verified)
    if voice is not None:
        # A JSON object, not SQL NULL nor a JSON null left by an older write.
        is_voice = func.coalesce(func.jsonb_typeof(Report.voice), "null") == "object"
        stmt = stmt.where(is_voice if voice else ~is_voice)
    if since is not None:
        stmt = stmt.where(Report.received_at >= since)
    if until is not None:
        stmt = stmt.where(Report.received_at < until)
    if q:
        stmt = stmt.where(_matches(q))
    if after is not None:
        at, last_id = after
        stmt = stmt.where(
            or_(Report.received_at < at, and_(Report.received_at == at, Report.id < last_id))
        )
    stmt = stmt.order_by(Report.received_at.desc(), Report.id.desc()).limit(limit + 1)
    return [_row(r) for r in (await db.execute(stmt)).all()]


async def get_report_row(
    db: AsyncSession, workspace_id: uuid.UUID, report_id: uuid.UUID
) -> ReportRow | None:
    stmt = _rows_query().where(Report.workspace_id == workspace_id, Report.id == report_id)
    values = (await db.execute(stmt)).one_or_none()
    return _row(values) if values is not None else None


async def list_photos(db: AsyncSession, report_id: uuid.UUID) -> list[ReportPhoto]:
    rows = await db.scalars(
        select(ReportPhoto)
        .where(ReportPhoto.report_id == report_id)
        .order_by(ReportPhoto.field_key, ReportPhoto.position)
    )
    return list(rows)


async def get_report_for_update(
    db: AsyncSession, workspace_id: uuid.UUID, report_id: uuid.UUID
) -> Report | None:
    return await db.scalar(
        select(Report)
        .where(Report.workspace_id == workspace_id, Report.id == report_id)
        .with_for_update()
    )


async def delete_values(db: AsyncSession, report_id: uuid.UUID) -> None:
    await db.execute(delete(ReportValue).where(ReportValue.report_id == report_id))


async def list_corrections(db: AsyncSession, report_id: uuid.UUID) -> list[ReportCorrection]:
    rows = await db.scalars(
        select(ReportCorrection)
        .where(ReportCorrection.report_id == report_id)
        .order_by(ReportCorrection.created_at)
    )
    return list(rows)


async def user_names(db: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not user_ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
    return {uid: name for uid, name in rows.all()}
