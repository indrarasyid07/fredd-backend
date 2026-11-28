"""The dashboard map (roadmap 5.2, dashboard.md "GET /reports/map").

One response feeds every map mode: regencies with counts and a colour, and up to 2.000 newest
located reports. The colour comes from the crop condition (alert threshold) or, for a structure,
from one single choice field. Health structures never send points, and leave out regions with
fewer than 5 reports, so a household cannot be found on the map.
"""

import json
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.dashboard import repository
from app.modules.dashboard.schemas import (
    BoundariesOut,
    BoundaryFeatureOut,
    DashboardRange,
    MapColorFieldOut,
    MapPointOut,
    MapRegionOut,
    MapValueOut,
    ReportMapOut,
)
from app.modules.forms import service as forms
from app.modules.forms.schemas import FieldDefinition, FormDefinition
from app.modules.workspaces import service as workspaces

MAX_POINTS = 2000
MIN_REGION_REPORTS = 5  # health structures: smaller regions are left out
APPROXIMATE_M = 50
BOUNDARY_TOLERANCE = 0.001  # degrees, about 100 m
MAX_BOUNDARIES = 100
PRIVATE_SECTORS = ("health",)
_RANGE_DAYS = {"today": 1, "7d": 7, "30d": 30}
_CONDITION_LABELS = {"healthy": "Sehat", "attention": "Perlu perhatian", "infected": "Terserang"}
_UNKNOWN = "unknown"
_UNKNOWN_LABEL = "Tanpa jawaban"


def _color_field(
    definition: FormDefinition | None, color_by: str | None
) -> tuple[str, FieldDefinition | None]:
    """("condition", field?) or ("choice", field), or ("none", None) when nothing can colour."""
    if definition is None:
        return "condition", None
    singles = [f for f in definition.fields if f.type == "single_choice"]
    if color_by:
        chosen = next((f for f in singles if f.key == color_by), None)
        if chosen is not None:
            return ("condition" if chosen.role == "condition" else "choice"), chosen
    for role in ("condition", "status"):
        chosen = next((f for f in singles if f.role == role), None)
        if chosen is not None:
            return ("condition" if role == "condition" else "choice"), chosen
    if singles:
        return "choice", singles[0]
    return "none", None


def _condition_color(by_value: dict[str, int], threshold: float) -> str:
    known = sum(n for v, n in by_value.items() if v != _UNKNOWN)
    if known == 0:
        return _UNKNOWN
    infected = by_value.get("infected", 0) / known
    attention = by_value.get("attention", 0) / known
    if infected >= threshold:
        return "infected"
    if infected + attention >= threshold:
        return "attention"
    return "healthy"


def _dominant(by_value: dict[str, int], order: list[str]) -> str:
    rank = {v: i for i, v in enumerate(order)}
    return max(by_value, key=lambda v: (by_value[v], -rank.get(v, len(rank))))


async def report_map(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    range_: DashboardRange = "today",
    form_id: uuid.UUID | None = None,
    color_by: str | None = None,
    values: list[str] | None = None,
    now: datetime | None = None,
) -> ReportMapOut:
    definition: FormDefinition | None = None
    sector: str | None = None
    if form_id is not None:
        form = await forms.get_form(db, workspace_id, form_id)  # another workspace's: 404
        sector = (form.settings or {}).get("sector_code")
        if form.current_version_id is not None:
            version = await forms.get_version_definition(db, workspace_id, form.current_version_id)
            definition = version.definition

    kind, field = _color_field(definition, color_by)
    now = now or now_utc()
    tz = ZoneInfo(await workspaces.get_timezone_name(db, workspace_id))
    local = now.astimezone(tz)
    today = datetime.combine(local.date(), datetime.min.time(), tz)
    start = today - timedelta(days=_RANGE_DAYS[range_] - 1)

    field_key = field.key if kind == "choice" and field is not None else None
    scope = repository.MapScope(
        workspace_id=workspace_id,
        start=start,
        end=now,
        form_id=form_id,
        field_key=field_key,
        values=tuple(values or ()),
    )
    totals = await repository.map_totals(db, scope)
    region_rows = await repository.map_regions(db, scope)
    latest = await repository.map_latest_per_region(db, scope)

    # Labels and order of the colouring values.
    if kind == "condition":
        labels = dict(_CONDITION_LABELS)
        if field is not None:
            labels.update({o.value: o.label for o in field.options if o.value in labels})
    elif field is not None:
        labels = {o.value: o.label for o in field.options}
    else:
        labels = {}
    order = list(labels)

    color_field = None
    if kind != "none":
        seen = {(v or _UNKNOWN) for v in totals}
        listed = [*order, *sorted(v for v in seen if v not in labels and v != _UNKNOWN)]
        if _UNKNOWN in seen:
            listed.append(_UNKNOWN)
        color_field = MapColorFieldOut(
            kind="condition" if kind == "condition" else "choice",
            key=field.key if field is not None else "condition",
            label=field.label if field is not None else "Kondisi tanaman",
            values=[
                MapValueOut(
                    value=v,
                    label=_UNKNOWN_LABEL if v == _UNKNOWN else labels.get(v, v),
                    count=sum(n for k, (n, _) in totals.items() if (k or _UNKNOWN) == v),
                )
                for v in listed
            ],
        )

    wanted = set(values or ())
    in_filter = [
        (n, located)
        for k, (n, located) in totals.items()
        if not wanted or (k or _UNKNOWN) in wanted
    ]
    total = sum(n for n, _ in in_filter)
    located = sum(lo for _, lo in in_filter)

    by_region: dict[uuid.UUID, dict[str, int]] = {}
    for region_id, value, n in region_rows:
        bucket = by_region.setdefault(region_id, {})
        bucket[value or _UNKNOWN] = bucket.get(value or _UNKNOWN, 0) + n

    private = sector in PRIVATE_SECTORS
    hidden = 0
    if private:
        kept = {r: b for r, b in by_region.items() if sum(b.values()) >= MIN_REGION_REPORTS}
        hidden = len(by_region) - len(kept)
        by_region = kept

    names = await repository.regions_by_id(db, list(by_region))
    threshold = await repository.map_alert_threshold(db, workspace_id)
    regions = []
    for region_id, bucket in by_region.items():
        name, lng, lat = names.get(region_id, ("Wilayah", None, None))
        if kind == "condition":
            color = _condition_color(bucket, threshold)
        elif kind == "choice":
            color = _dominant(bucket, order)
        else:
            color = _UNKNOWN
        regions.append(
            MapRegionOut(
                region_id=region_id,
                name=name,
                centroid=[lng, lat] if lng is not None and lat is not None else None,
                count=sum(bucket.values()),
                by_value=bucket,
                color=color,
                latest_report_id=None if private else latest.get(region_id),
            )
        )
    regions.sort(key=lambda r: (-r.count, r.name))

    points: list[MapPointOut] = []
    truncated = False
    if not private:
        rows = await repository.map_points(db, scope, MAX_POINTS)
        truncated = len(rows) > MAX_POINTS
        points = [
            MapPointOut(
                id=report_id,
                lat=lat,
                lng=lng,
                value=value if kind != "none" else None,
                approximate=accuracy is None or accuracy > APPROXIMATE_M,
            )
            for report_id, lat, lng, accuracy, value in rows[:MAX_POINTS]
        ]

    return ReportMapOut(
        range=range_,
        total=total,
        located=located,
        color_field=color_field,
        regions=regions,
        points=points,
        truncated=truncated,
        privacy="regions_only" if private else "full",
        hidden_regions=hidden,
    )


async def region_boundaries(db: AsyncSession, ids: list[uuid.UUID]) -> BoundariesOut:
    """Simplified outlines of the given regions (platform reference data, the same for every
    workspace), so the client fetches only what the map shows and caches it."""
    rows = await repository.boundaries(db, ids[:MAX_BOUNDARIES], BOUNDARY_TOLERANCE)
    return BoundariesOut(
        features=[
            BoundaryFeatureOut(id=rid, properties={"name": name}, geometry=json.loads(geojson))
            for rid, name, geojson in rows
            if geojson
        ]
    )
