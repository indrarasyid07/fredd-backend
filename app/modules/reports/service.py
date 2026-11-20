"""Creating field reports (roadmap 4.0, antarmuka 3 in TEAM-WORKFLOW.md).

The conversation engine calls `create_report` when a worker confirms the summary, in the same
transaction that marks the conversation `submitted` (this function flushes, the caller commits).
Every filter column is copied from the answers here, once, so the dashboard reads plain columns:
condition and area from the fields with that role, the point from the first location answer,
the region from the point, and the 50 m plot key for "unique plots".
"""

import hashlib
import math
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.forms.constants import CONDITION_VALUES
from app.modules.forms.schemas import FieldDefinition, FormDefinition
from app.modules.reference_data import service as reference_data
from app.modules.reports import repository
from app.modules.reports.models import Report, ReportPhoto

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
    await db.flush()
    return report


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
