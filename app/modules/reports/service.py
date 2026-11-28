"""Creating field reports (roadmap 4.0, antarmuka 3 in TEAM-WORKFLOW.md).

The conversation engine calls `create_report` when a worker confirms the summary, in the same
transaction that marks the conversation `submitted` (this function flushes, the caller commits).
Every filter column is copied from the answers here, once, so the dashboard reads plain columns:
condition and area from the fields with that role, the point from the first location answer,
the region from the point, and the 50 m plot key for "unique plots".
"""

import asyncio
import hashlib
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.pagination import InvalidCursor
from app.core.storage import get_storage
from app.core.time import now_utc
from app.modules.ai import extraction
from app.modules.ai.extraction import CONFIDENT
from app.modules.audit import service as audit
from app.modules.forms import service as forms
from app.modules.forms.constants import CONDITION_VALUES
from app.modules.forms.schemas import FieldDefinition, FormDefinition
from app.modules.reference_data import service as reference_data
from app.modules.reports import exports, repository
from app.modules.reports.errors import (
    ExportTooLarge,
    FieldNotCorrectable,
    InvalidCorrection,
    ReportAlreadyVerified,
    ReportNotFound,
)
from app.modules.reports.models import Report, ReportCorrection, ReportPhoto, ReportValue
from app.modules.reports.schemas import (
    CorrectValueRequest,
    NamedRef,
    ReportCorrectionOut,
    ReportDetailOut,
    ReportFieldOut,
    ReportFormOut,
    ReportListItemOut,
    ReportLocationOut,
    ReportPhotoOut,
    ReportReviewOut,
    ReportVerificationOut,
    ReportVoiceOut,
    VoiceFieldOut,
)

# "Titik lahan": a point rounded to a 50 m grid, per worker and structure (dashboard.md).
PLOT_GRID_METERS = 50
_METERS_PER_DEGREE = 111_320
_PHOTO_TYPES = ("photo",)


def report_code(period: str, number: int) -> str:
    """LP-YYMM-NNNN; past 9999 in a month the number simply grows (LP-2611-10000)."""
    return f"LP-{period}-{number:04d}"


async def create_report(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    form_id: uuid.UUID,
    form_version_id: uuid.UUID,
    definition: FormDefinition,
    extension_worker_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    answers: dict[str, Any],
    needs_review: bool = False,
    review_reasons: list[str] | tuple[str, ...] = (),
    received_at: datetime | None = None,
    voice: dict[str, Any] | None = None,
) -> Report:
    received = received_at or now_utc()
    tz = await repository.get_timezone(db, workspace_id)
    period = received.astimezone(tz).strftime("%y%m")
    number = await repository.take_code_number(db, workspace_id, period)

    point = _first_point(definition, answers)
    region_id = None
    if point is not None:
        path = await reference_data.locate(db, lat=point[0], lng=point[1])
        region = path.district or path.regency
        region_id = region.id if region else None

    report = Report(
        workspace_id=workspace_id,
        code=report_code(period, number),
        form_id=form_id,
        form_version_id=form_version_id,
        extension_worker_id=extension_worker_id,
        conversation_id=conversation_id,
        answers=answers,
        latitude=point[0] if point else None,
        longitude=point[1] if point else None,
        accuracy_m=point[2] if point else None,
        region_id=region_id,
        condition=_condition(definition, answers),
        area_ha=_area(definition, answers),
        plot_key=plot_key(point[0], point[1], extension_worker_id, form_id) if point else None,
        complete=is_complete(definition, answers),
        needs_review=needs_review,
        review_reasons=list(review_reasons),
        received_at=received,
        voice=voice,
    )
    db.add(report)
    await db.flush()
    for f in definition.fields:
        if f.type in _PHOTO_TYPES:
            for position, ref in enumerate(answers.get(f.key) or []):
                if isinstance(ref, str) and ref:
                    db.add(
                        ReportPhoto(
                            report_id=report.id, field_key=f.key, position=position, object_key=ref
                        )
                    )
    db.add_all(_values(report, definition, answers))
    await db.flush()
    return report


def _values(
    report: Report, definition: FormDefinition, answers: dict[str, Any]
) -> list[ReportValue]:
    """Every choice and number answer as a row for dashboard widgets (D17). Values that do not
    read as their type (a typo stored by an older engine) are left out, never guessed."""
    rows: list[ReportValue] = []

    def row(key: str, *, choice: str | None = None, number: Decimal | None = None) -> None:
        rows.append(
            ReportValue(
                workspace_id=report.workspace_id,
                report_id=report.id,
                form_id=report.form_id,
                field_key=key,
                choice=choice,
                number=number,
                received_at=report.received_at,
            )
        )

    for f in definition.fields:
        value = answers.get(f.key)
        if value is None:
            continue
        if f.type == "single_choice" and isinstance(value, str):
            row(f.key, choice=value)
        elif f.type == "multi_choice" and isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    row(f.key, choice=item)
        elif f.type == "number":
            try:
                number = Decimal(str(value))
            except InvalidOperation:
                continue
            if number.is_finite():
                row(f.key, number=number)
    return rows


def _answered(value: Any) -> bool:
    return value not in (None, "", [], {})


def is_complete(definition: FormDefinition, answers: dict[str, Any]) -> bool:
    """Every required field has an answer (skipped optional fields do not count against it)."""
    return all(_answered(answers.get(f.key)) for f in definition.fields if f.required)


def _role(definition: FormDefinition, role: str, answers: dict[str, Any]) -> Any:
    field: FieldDefinition | None = definition.field_with_role(role)
    return answers.get(field.key) if field else None


def _condition(definition: FormDefinition, answers: dict[str, Any]) -> str | None:
    value = _role(definition, "condition", answers)
    return value if value in CONDITION_VALUES else None


def _area(definition: FormDefinition, answers: dict[str, Any]) -> Decimal | None:
    value = _role(definition, "area", answers)
    if value is None:
        return None
    try:
        area = Decimal(str(value))
    except InvalidOperation:
        return None
    return area if area.is_finite() and area >= 0 else None


def _first_point(
    definition: FormDefinition, answers: dict[str, Any]
) -> tuple[float, float, float | None] | None:
    """The first location answer that is a GPS point ({lat, lng, accuracy_m}); a typed place
    name ({name}) has no point."""
    for f in definition.fields:
        if f.type != "location":
            continue
        value = answers.get(f.key)
        if not isinstance(value, dict):
            continue
        try:
            lat, lng = float(value["lat"]), float(value["lng"])
        except KeyError, TypeError, ValueError:
            continue
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            accuracy = value.get("accuracy_m")
            return lat, lng, float(accuracy) if isinstance(accuracy, int | float) else None
    return None


def plot_key(lat: float, lng: float, worker_id: uuid.UUID, form_id: uuid.UUID) -> str:
    """Same 50 m cell, same worker and structure → same key."""
    step_lat = PLOT_GRID_METERS / _METERS_PER_DEGREE
    step_lng = PLOT_GRID_METERS / (_METERS_PER_DEGREE * max(math.cos(math.radians(lat)), 0.01))
    cell = f"{math.floor(lat / step_lat)}:{math.floor(lng / step_lng)}"
    return hashlib.sha256(f"{worker_id}:{form_id}:{cell}".encode()).hexdigest()[:32]


# --- Reading (roadmap 4.3) ----------------------------------------------------------------------

_CONDITION_LABELS = {"healthy": "Sehat", "attention": "Perlu perhatian", "infected": "Terserang"}
_MEDIA_WORDS = {
    "photo": "foto",
    "video": "video",
    "voice": "pesan suara",
    "document": "berkas",
    "signature": "tanda tangan",
}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
SKIPPED = "Dilewati"


async def list_reports(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    form_id: uuid.UUID | None = None,
    extension_worker_id: uuid.UUID | None = None,
    region_id: uuid.UUID | None = None,
    conditions: list[str] | None = None,
    needs_review: bool | None = None,
    verified: bool | None = None,
    voice: bool | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    after: list[str] | None = None,
    limit: int = 20,
    q: str | None = None,
) -> tuple[list[ReportListItemOut], list[str] | None]:
    """A page of reports (newest first) and the next cursor's values (None on the last page)."""
    rows = await repository.list_reports(
        db,
        workspace_id,
        form_id=form_id,
        extension_worker_id=extension_worker_id,
        region_id=region_id,
        conditions=conditions,
        needs_review=needs_review,
        verified=verified,
        voice=voice,
        since=since,
        until=until,
        after=_parse_after(after),
        limit=limit,
        q=q.strip() if q and q.strip() else None,
    )
    page = rows[:limit]
    more = None
    if len(rows) > limit:
        last = page[-1].report
        more = [last.received_at.isoformat(), str(last.id)]
    return [_list_item(r) for r in page], more


async def get_report_detail(
    db: AsyncSession, workspace_id: uuid.UUID, report_id: uuid.UUID
) -> ReportDetailOut:
    row = await repository.get_report_row(db, workspace_id, report_id)
    if row is None:
        raise ReportNotFound()
    report = row.report
    # The version the report was made with: an old report keeps its old labels and order.
    version = await forms.get_version_definition(
        db, workspace_id, report.form_version_id, published_only=False
    )
    definition = version.definition
    location = None
    if report.latitude is not None and report.longitude is not None:
        location = ReportLocationOut(
            lat=report.latitude, lng=report.longitude, accuracy_m=report.accuracy_m
        )
    return ReportDetailOut(
        id=report.id,
        code=report.code,
        form=ReportFormOut(id=report.form_id, name=row.form_name, version=version.version),
        worker=NamedRef(id=report.extension_worker_id, name=row.worker_name),
        channel=_channel(row),
        received_at=report.received_at,
        location=location,
        region=_region(row),
        condition=report.condition,  # type: ignore[arg-type]  # checked by the table
        area_ha=float(report.area_ha) if report.area_ha is not None else None,
        complete=report.complete,
        fields=[_field(f, report.answers.get(f.key)) for f in definition.fields],
        photos=await _photos(db, report.id),
        review=ReportReviewOut(
            needs_review=report.needs_review,
            reasons=[_reason(definition, r) for r in report.review_reasons],
        ),
        voice=await _voice(report.voice, definition),
        verification=await _verification(db, report),
        corrections=await _corrections(db, report.id, definition),
    )


def _parse_after(after: list[str] | None) -> tuple[datetime, uuid.UUID] | None:
    if after is None:
        return None
    try:
        return datetime.fromisoformat(after[0]), uuid.UUID(after[1])
    except ValueError:
        raise InvalidCursor() from None


def _channel(row: repository.ReportRow) -> Literal["telegram", "whatsapp"]:
    return "telegram" if row.telegram_user_id else "whatsapp"


def _region(row: repository.ReportRow) -> NamedRef | None:
    region_id = row.report.region_id
    if region_id is None or row.region_name is None:
        return None
    return NamedRef(id=region_id, name=row.region_name)


def _list_item(row: repository.ReportRow) -> ReportListItemOut:
    report = row.report
    return ReportListItemOut(
        id=report.id,
        code=report.code,
        form=NamedRef(id=report.form_id, name=row.form_name),
        worker=NamedRef(id=report.extension_worker_id, name=row.worker_name),
        channel=_channel(row),
        region=_region(row),
        condition=report.condition,  # type: ignore[arg-type]  # checked by the table
        area_ha=float(report.area_ha) if report.area_ha is not None else None,
        photo_count=row.photo_count,
        needs_review=report.needs_review,
        complete=report.complete,
        received_at=report.received_at,
        transcript=(report.voice or {}).get("transcript"),
        verified=report.verified_at is not None,
    )


async def _voice(voice: dict[str, Any] | None, definition: FormDefinition) -> ReportVoiceOut | None:
    """The voice note behind a report, with a short-lived link to the recording and, per field
    in the version's order, the words heard and the confidence."""
    if not voice or not voice.get("transcript"):
        return None
    seconds = settings.storage_presign_expiry_seconds
    audio = voice.get("audio")
    url = await get_storage().signed_url(audio, seconds) if audio else None
    heard: dict[str, str] = voice.get("heard") or {}
    confidence: dict[str, float] = voice.get("confidence") or {}
    fields = [
        VoiceFieldOut(
            key=f.key,
            label=f.label,
            heard=heard[f.key],
            confidence=float(confidence.get(f.key, 0)),
            confident=float(confidence.get(f.key, 0)) >= CONFIDENT,
        )
        for f in definition.fields
        if f.key in heard
    ]
    return ReportVoiceOut(
        transcript=str(voice["transcript"]),
        audio_url=url,
        audio_expires_at=now_utc() + timedelta(seconds=seconds) if url else None,
        fields=fields,
    )


async def _photos(db: AsyncSession, report_id: uuid.UUID) -> list[ReportPhotoOut]:
    """Each photo with a short-lived signed link. A photo still kept as a Telegram reference
    (its copy failed) has no link yet."""
    seconds = settings.storage_presign_expiry_seconds
    storage = get_storage()
    out: list[ReportPhotoOut] = []
    for photo in await repository.list_photos(db, report_id):
        url = None
        if not photo.object_key.startswith("telegram:"):
            url = await storage.signed_url(photo.object_key, seconds)
        out.append(
            ReportPhotoOut(
                id=photo.id,
                field_key=photo.field_key,
                position=photo.position,
                url=url,
                expires_at=now_utc() + timedelta(seconds=seconds) if url else None,
                ai_note=photo.ai_note,
            )
        )
    return out


def _field(f: FieldDefinition, value: Any) -> ReportFieldOut:
    return ReportFieldOut(
        key=f.key, label=f.label, type=f.type, value=value, display=display(f, value), unit=f.unit
    )


def display(f: FieldDefinition, value: Any) -> str:
    """An answer as it reads in Indonesian."""
    if not _answered(value):
        return SKIPPED
    if f.type == "number":
        text = _number(value)
        return f"{text} {f.unit}" if f.unit else text
    if f.type in ("single_choice", "multi_choice"):
        values = value if isinstance(value, list) else [value]
        return ", ".join(_option_label(f, v) for v in values)
    if f.type == "datetime":
        return _date(str(value))
    if f.type == "location":
        return _place(value)
    if f.type in _MEDIA_WORDS:
        count = len(value) if isinstance(value, list) else 1
        return f"{count} {_MEDIA_WORDS[f.type]}"
    return str(value)


def _number(value: Any) -> str:
    try:
        number = Decimal(str(value)).normalize()
    except InvalidOperation:
        return str(value)
    return f"{number:f}".replace(".", ",")


def _option_label(f: FieldDefinition, value: Any) -> str:
    for option in f.options:
        if option.value == value:
            return option.label
    return _CONDITION_LABELS.get(str(value), str(value))


def _date(value: str) -> str:
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return value
    text = f"{when.day} {_MONTHS[when.month - 1]} {when.year}"
    if "T" in value:
        text += f", {when:%H.%M}"
    return text


def _place(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value)
    if value.get("name"):
        return str(value["name"])
    try:
        text = f"{float(value['lat']):.5f}, {float(value['lng']):.5f}"
    except KeyError, TypeError, ValueError:
        return str(value)
    accuracy = value.get("accuracy_m")
    return f"{text} (akurasi {round(float(accuracy))} m)" if accuracy else text


def _reason(definition: FormDefinition, reason: str) -> str:
    """Why a report waits for review: "review_above:<field>" or "rule:<index>"."""
    kind, _, ref = reason.partition(":")
    if kind == "review_above" and (f := definition.field(ref)) and f.review_above is not None:
        limit = _number(f.review_above)
        return f"{f.label} di atas {limit} {f.unit}" if f.unit else f"{f.label} di atas {limit}"
    if kind == "rule" and ref.isdigit() and int(ref) < len(definition.rules):
        rule = definition.rules[int(ref)]
        f = definition.field(rule.if_.field)
        if f is not None:
            return f"Aturan: {f.label} = {display(f, rule.if_.equals)}"
    return "Perlu ditinjau"


# --- Corrections and verification (roadmap 12.5) -------------------------------------------------

_CORRECTABLE = ("short_text", "long_text", "number", "single_choice", "multi_choice", "datetime")


async def correct_value(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    report_id: uuid.UUID,
    user_id: uuid.UUID,
    request: CorrectValueRequest,
) -> ReportDetailOut:
    """A supervisor replaces one value (reason required). The typed value is read like a spoken
    one; the filter columns and dashboard values follow the new answers."""
    report = await repository.get_report_for_update(db, workspace_id, report_id)
    if report is None:
        raise ReportNotFound()
    if report.verified_at is not None:
        raise ReportAlreadyVerified()
    version = await forms.get_version_definition(
        db, workspace_id, report.form_version_id, published_only=False
    )
    definition = version.definition
    f = definition.field(request.field_key)
    if f is None or f.type not in _CORRECTABLE:
        raise FieldNotCorrectable(field="field_key")
    read = extraction.read_value(f, request.value)
    if read is None or read.value is None:
        doubt = read.doubt if read is not None else None
        raise InvalidCorrection(f"{doubt}." if doubt else None, field="value")
    if read.doubt == "Satuan yang terdengar bukan " + (f.unit or ""):
        raise InvalidCorrection(f"Satuannya harus {f.unit}.", field="value")

    old = report.answers.get(f.key)
    answers = {**report.answers, f.key: read.value}  # a new dict, so the JSONB change is saved
    report.answers = answers
    report.condition = _condition(definition, answers)
    report.area_ha = _area(definition, answers)
    report.complete = is_complete(definition, answers)
    await repository.delete_values(db, report.id)
    db.add_all(_values(report, definition, answers))
    db.add(
        ReportCorrection(
            workspace_id=workspace_id,
            report_id=report.id,
            field_key=f.key,
            old_value=old,
            new_value=read.value,
            reason=request.reason.strip(),
            user_id=user_id,
        )
    )
    await audit.record(
        db,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="report.corrected",
        target=str(report.id),
        details={"field": f.key, "old": old, "new": read.value, "reason": request.reason.strip()},
    )
    await db.commit()
    return await get_report_detail(db, workspace_id, report_id)


async def verify_report(
    db: AsyncSession, workspace_id: uuid.UUID, report_id: uuid.UUID, user_id: uuid.UUID
) -> ReportDetailOut:
    report = await repository.get_report_for_update(db, workspace_id, report_id)
    if report is None:
        raise ReportNotFound()
    if report.verified_at is not None:
        raise ReportAlreadyVerified()
    report.verified_at = now_utc()
    report.verified_by_user_id = user_id
    await audit.record(
        db,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="report.verified",
        target=str(report.id),
        details={"code": report.code},
    )
    await db.commit()
    return await get_report_detail(db, workspace_id, report_id)


async def _verification(db: AsyncSession, report: Report) -> ReportVerificationOut:
    by = report.verified_by_user_id
    names = await repository.user_names(db, {by}) if by else {}
    return ReportVerificationOut(
        verified=report.verified_at is not None,
        verified_at=report.verified_at,
        verified_by=names.get(by) if by else None,
    )


async def _corrections(
    db: AsyncSession, report_id: uuid.UUID, definition: FormDefinition
) -> list[ReportCorrectionOut]:
    rows = await repository.list_corrections(db, report_id)
    names = await repository.user_names(db, {r.user_id for r in rows if r.user_id})
    out = []
    for r in rows:
        f = definition.field(r.field_key)
        out.append(
            ReportCorrectionOut(
                field_key=r.field_key,
                label=f.label if f else r.field_key,
                old_display=display(f, r.old_value) if f else str(r.old_value),
                new_display=display(f, r.new_value) if f else str(r.new_value),
                reason=r.reason,
                by=names.get(r.user_id) if r.user_id else None,
                at=r.created_at,
            )
        )
    return out


# --- Voice Lab export (roadmap 12.6) ------------------------------------------------------------

# Written in the request (B-0xx); the export job of dashboard.md takes over past this.
MAX_VOICE_EXPORT_ROWS = 5000


@dataclass(frozen=True)
class ExportFile:
    filename: str
    media_type: str
    content: bytes
    row_count: int


async def export_voice(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    form_id: uuid.UUID,
    fmt: exports.ExportFormat,
    since: datetime | None = None,
    until: datetime | None = None,
) -> ExportFile:
    """Verified voice reports of one structure, oldest first, as a file; logged in the audit
    trail. Unverified reports are never in it: only what a supervisor confirmed leaves Fluctuz."""
    form = await forms.get_form(db, workspace_id, form_id)
    rows = await repository.list_reports(
        db,
        workspace_id,
        form_id=form_id,
        extension_worker_id=None,
        region_id=None,
        conditions=None,
        needs_review=None,
        verified=True,
        voice=True,
        since=since,
        until=until,
        after=None,
        limit=MAX_VOICE_EXPORT_ROWS,
    )
    if len(rows) > MAX_VOICE_EXPORT_ROWS:
        raise ExportTooLarge()
    rows.reverse()

    version_ids = {r.report.form_version_id for r in rows}
    if form.current_version_id is not None:
        version_ids.add(form.current_version_id)
    versions = [
        await forms.get_version_definition(db, workspace_id, v, published_only=False)
        for v in version_ids
    ]
    versions.sort(key=lambda v: v.version, reverse=True)
    fields = exports.columns([v.definition for v in versions])

    zone = await repository.get_timezone(db, workspace_id)
    names = await repository.user_names(
        db, {r.report.verified_by_user_id for r in rows if r.report.verified_by_user_id}
    )
    export_rows = [
        exports.ExportRow(
            code=r.report.code,
            analyst=r.worker_name,
            received_at=r.report.received_at.astimezone(zone),
            verified_by=names.get(r.report.verified_by_user_id)
            if r.report.verified_by_user_id
            else None,
            verified_at=r.report.verified_at.astimezone(zone) if r.report.verified_at else None,
            answers=r.report.answers,
        )
        for r in rows
    ]
    content = await asyncio.to_thread(exports.write, fmt, exports.table(fields, export_rows))
    await audit.record(
        db,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="report.voice_exported",
        target=str(form_id),
        details={
            "format": fmt,
            "row_count": len(rows),
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
    )
    await db.commit()
    return ExportFile(
        filename=exports.filename(form.name, now_utc().astimezone(zone), fmt),
        media_type=exports.MEDIA_TYPES[fmt],
        content=content,
        row_count=len(rows),
    )
