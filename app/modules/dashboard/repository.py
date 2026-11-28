"""Aggregates for the dashboard. Every query is filtered by workspace and reads plain report
columns (copied once at creation), never the answers JSON. Days are counted in the workspace's
time zone; the caller passes the instants that bound them."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import String, TextClause, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

# A report's region may be a district; dashboard areas are regencies (its parent).
_REGENCY = """
    from reports x
    join reference_data r on r.id = x.region_id
    left join reference_data p on p.id = r.parent_id
"""
_REGENCY_ID = "case when r.level = 'district' then p.id else r.id end"
_REGENCY_NAME = "case when r.level = 'district' then p.value else r.value end"


_FORM = "and (cast(:form as uuid) is null or form_id = :form) "


async def count_between(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    start: datetime,
    end: datetime,
    form_id: uuid.UUID | None = None,
) -> int:
    result = await db.execute(
        text(
            "select count(*) from reports "
            "where workspace_id = :ws and received_at >= :start and received_at < :end " + _FORM
        ),
        {"ws": workspace_id, "start": start, "end": end, "form": form_id},
    )
    return int(result.scalar_one())


async def count_per_day(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    tz: str,
    start: datetime,
    end: datetime,
    form_id: uuid.UUID | None = None,
) -> dict[date, int]:
    rows = await db.execute(
        text(
            "select (received_at at time zone :tz)::date as day, count(*) from reports "
            "where workspace_id = :ws and received_at >= :start and received_at < :end "
            + _FORM
            + "group by day"
        ),
        {"ws": workspace_id, "tz": tz, "start": start, "end": end, "form": form_id},
    )
    return {day: int(n) for day, n in rows.all()}


async def count_per_hour(
    db: AsyncSession, workspace_id: uuid.UUID, tz: str, start: datetime, end: datetime
) -> dict[tuple[date, int], int]:
    """Reports per (local day, local hour 0-23), for the busiest-hours heatmap."""
    rows = await db.execute(
        text(
            "select (received_at at time zone :tz)::date as day, "
            "extract(hour from received_at at time zone :tz)::int as hour, count(*) "
            "from reports "
            "where workspace_id = :ws and received_at >= :start and received_at < :end "
            "group by day, hour"
        ),
        {"ws": workspace_id, "tz": tz, "start": start, "end": end},
    )
    return {(day, hour): int(n) for day, hour, n in rows.all()}


async def count_per_channel(
    db: AsyncSession, workspace_id: uuid.UUID, start: datetime, end: datetime
) -> dict[str, int]:
    rows = await db.execute(
        text(
            "select case when w.telegram_user_id is null then 'whatsapp' else 'telegram' end, "
            "count(*) from reports x join extension_workers w on w.id = x.extension_worker_id "
            "where x.workspace_id = :ws and x.received_at >= :start and x.received_at < :end "
            "group by 1"
        ),
        {"ws": workspace_id, "start": start, "end": end},
    )
    return {channel: int(n) for channel, n in rows.all()}


async def worker_counts(
    db: AsyncSession, workspace_id: uuid.UUID, today: datetime, now: datetime
) -> tuple[int, int]:
    """(active workers, active workers with a report today)."""
    row = await db.execute(
        text(
            "select count(*), count(*) filter (where exists ("
            "  select 1 from reports x where x.extension_worker_id = w.id"
            "  and x.received_at >= :today and x.received_at < :now)) "
            "from extension_workers w where w.workspace_id = :ws and w.status = 'active'"
        ),
        {"ws": workspace_id, "today": today, "now": now},
    )
    total, active = row.one()
    return int(total), int(active)


async def monitored_land(
    db: AsyncSession, workspace_id: uuid.UUID, start: datetime, end: datetime
) -> tuple[Decimal, int, int]:
    """(hectares, plots, regencies) from the newest report of each plot in the window."""
    row = await db.execute(
        text(
            "with latest as ("
            "  select distinct on (plot_key) area_ha, region_id from reports"
            "  where workspace_id = :ws and received_at >= :start and received_at < :end"
            "  and plot_key is not null order by plot_key, received_at desc) "
            "select coalesce(sum(l.area_ha), 0), count(*), "
            f"count(distinct {_REGENCY_ID}) "
            "from latest l left join reference_data r on r.id = l.region_id "
            "left join reference_data p on p.id = r.parent_id"
        ),
        {"ws": workspace_id, "start": start, "end": end},
    )
    area, points, regencies = row.one()
    return Decimal(area), int(points), int(regencies)


async def completion(
    db: AsyncSession, workspace_id: uuid.UUID, start: datetime, end: datetime
) -> tuple[int, int]:
    """(complete reports, reports) in the window."""
    row = await db.execute(
        text(
            "select count(*) filter (where complete), count(*) from reports "
            "where workspace_id = :ws and received_at >= :start and received_at < :end"
        ),
        {"ws": workspace_id, "start": start, "end": end},
    )
    complete, total = row.one()
    return int(complete), int(total)


async def count_per_condition(
    db: AsyncSession, workspace_id: uuid.UUID, start: datetime, end: datetime
) -> dict[str | None, int]:
    rows = await db.execute(
        text(
            "select condition, count(*) from reports "
            "where workspace_id = :ws and received_at >= :start and received_at < :end "
            "group by condition"
        ),
        {"ws": workspace_id, "start": start, "end": end},
    )
    return {condition: int(n) for condition, n in rows.all()}


async def top_regencies(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    start: datetime,
    end: datetime,
    *,
    condition: str | None,
    limit: int,
    form_id: uuid.UUID | None = None,
) -> list[tuple[uuid.UUID, str, int]]:
    """Regencies with the most reports in the window (of one condition and one structure, when
    given)."""
    rows = await db.execute(
        text(
            f"select {_REGENCY_ID} as id, {_REGENCY_NAME} as name, count(*) as n {_REGENCY}"
            "where x.workspace_id = :ws and x.received_at >= :start and x.received_at < :end "
            "and (cast(:condition as text) is null or x.condition = :condition) "
            "and (cast(:form as uuid) is null or x.form_id = :form) "
            "group by 1, 2 order by n desc, name limit :limit"
        ),
        {
            "ws": workspace_id,
            "start": start,
            "end": end,
            "condition": condition,
            "limit": limit,
            "form": form_id,
        },
    )
    return [(rid, name, int(n)) for rid, name, n in rows.all() if rid is not None]


async def setup_flags(db: AsyncSession, workspace_id: uuid.UUID) -> tuple[bool, bool, bool]:
    """(has a structure, has an active worker, has a report)."""
    row = await db.execute(
        text(
            "select exists (select 1 from forms where workspace_id = :ws), "
            "exists (select 1 from extension_workers where workspace_id = :ws "
            "  and status = 'active'), "
            "exists (select 1 from reports where workspace_id = :ws)"
        ),
        {"ws": workspace_id},
    )
    forms, workers, reports = row.one()
    return bool(forms), bool(workers), bool(reports)


async def choice_counts(
    db: AsyncSession, workspace_id: uuid.UUID, form_id: uuid.UUID, start: datetime, end: datetime
) -> tuple[dict[tuple[str, str], int], dict[str, int]]:
    """Per (field, value): reports that chose it; and per field: reports that answered it."""
    rows = await db.execute(
        text(
            "select field_key, choice, count(distinct report_id) from report_values "
            "where workspace_id = :ws and form_id = :form and choice is not null "
            "and received_at >= :start and received_at < :end "
            "group by grouping sets ((field_key, choice), (field_key))"
        ),
        {"ws": workspace_id, "form": form_id, "start": start, "end": end},
    )
    counts: dict[tuple[str, str], int] = {}
    answered: dict[str, int] = {}
    for field_key, choice, n in rows.all():
        if choice is None:
            answered[field_key] = int(n)
        else:
            counts[(field_key, choice)] = int(n)
    return counts, answered


async def number_stats(
    db: AsyncSession, workspace_id: uuid.UUID, form_id: uuid.UUID, start: datetime, end: datetime
) -> dict[str, tuple[int, Decimal, Decimal, Decimal, Decimal]]:
    """Per number field: (answers, sum, average, minimum, maximum)."""
    rows = await db.execute(
        text(
            "select field_key, count(*), sum(number), avg(number), min(number), max(number) "
            "from report_values "
            "where workspace_id = :ws and form_id = :form and number is not null "
            "and received_at >= :start and received_at < :end "
            "group by field_key"
        ),
        {"ws": workspace_id, "form": form_id, "start": start, "end": end},
    )
    return {key: (int(n), total, avg, low, high) for key, n, total, avg, low, high in rows.all()}


# --- One structure's headline numbers (roadmap 11.3a) -------------------------------------------


async def form_kpis(
    db: AsyncSession, workspace_id: uuid.UUID, form_id: uuid.UUID, start: datetime, end: datetime
) -> tuple[int, int, int, int]:
    """(reports, complete, needing review, distinct workers) of one structure in the window."""
    row = await db.execute(
        text(
            "select count(*), count(*) filter (where complete), "
            "count(*) filter (where needs_review), count(distinct extension_worker_id) "
            "from reports where workspace_id = :ws and form_id = :form "
            "and received_at >= :start and received_at < :end"
        ),
        {"ws": workspace_id, "form": form_id, "start": start, "end": end},
    )
    total, complete, review, workers = row.one()
    return int(total), int(complete), int(review), int(workers)


# --- Map (roadmap 5.2) ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MapScope:
    """Which reports the map draws, and the single choice field (or condition) colouring them."""

    workspace_id: uuid.UUID
    start: datetime
    end: datetime
    form_id: uuid.UUID | None
    # None: `reports.condition`; else a single choice field key read from report_values.
    field_key: str | None
    # Only these values ("unknown" = no answer); empty = all.
    values: tuple[str, ...] = ()


def _map_base(scope: MapScope) -> tuple[str, dict[str, Any]]:
    value = "rv.choice" if scope.field_key else "x.condition"
    join = (
        "left join report_values rv on rv.report_id = x.id and rv.field_key = :key "
        if scope.field_key
        else ""
    )
    sql = (
        "with base as ("
        f" select x.id, x.received_at, x.latitude, x.longitude, x.accuracy_m, {value} as value,"
        f" {_REGENCY_ID} as regency_id"
        " from reports x " + join + " left join reference_data r on r.id = x.region_id"
        " left join reference_data p on p.id = r.parent_id"
        " where x.workspace_id = :ws and x.received_at >= :start and x.received_at < :end"
        " and (cast(:form as uuid) is null or x.form_id = :form)"
        ") , scoped as (select * from base"
        " where cardinality(:values) = 0 or coalesce(value, 'unknown') = any(:values)) "
    )
    params: dict[str, Any] = {
        "ws": scope.workspace_id,
        "start": scope.start,
        "end": scope.end,
        "form": scope.form_id,
        "key": scope.field_key,
        "values": list(scope.values),
    }
    return sql, params


def _bind(sql: str) -> TextClause:
    return text(sql).bindparams(bindparam("values", type_=ARRAY(String)))


async def map_totals(db: AsyncSession, scope: MapScope) -> dict[str | None, tuple[int, int]]:
    """Per value: (reports, reports with coordinates), over the whole range (no value filter on
    the legend, so every value keeps its count)."""
    base, params = _map_base(scope)
    rows = await db.execute(
        _bind(
            base + "select value, count(*), count(*) filter (where latitude is not null) "
            "from base group by value"
        ),
        params,
    )
    return {v: (int(n), int(located)) for v, n, located in rows.all()}


async def map_regions(db: AsyncSession, scope: MapScope) -> list[tuple[uuid.UUID, str | None, int]]:
    """(regency, value, reports) of the filtered reports."""
    base, params = _map_base(scope)
    rows = await db.execute(
        _bind(
            base + "select regency_id, value, count(*) from scoped "
            "where regency_id is not null group by 1, 2"
        ),
        params,
    )
    return [(rid, v, int(n)) for rid, v, n in rows.all()]


async def map_latest_per_region(db: AsyncSession, scope: MapScope) -> dict[uuid.UUID, uuid.UUID]:
    base, params = _map_base(scope)
    rows = await db.execute(
        _bind(
            base + "select distinct on (regency_id) regency_id, id from scoped "
            "where regency_id is not null order by regency_id, received_at desc"
        ),
        params,
    )
    return {rid: report_id for rid, report_id in rows.all()}


async def map_points(
    db: AsyncSession, scope: MapScope, limit: int
) -> list[tuple[uuid.UUID, float, float, float | None, str | None]]:
    """Newest located reports first, `limit` + 1 rows so the caller can tell there were more."""
    base, params = _map_base(scope)
    rows = await db.execute(
        _bind(
            base + "select id, latitude, longitude, accuracy_m, value from scoped "
            "where latitude is not null and longitude is not null "
            "order by received_at desc, id desc limit :limit"
        ),
        {**params, "limit": limit + 1},
    )
    return [(i, float(lat), float(lng), acc, v) for i, lat, lng, acc, v in rows.all()]


async def regions_by_id(
    db: AsyncSession, ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, float | None, float | None]]:
    """(name, centroid lng, centroid lat) of platform regions."""
    if not ids:
        return {}
    rows = await db.execute(
        text(
            "select id, value, ST_X(centroid), ST_Y(centroid) from reference_data "
            "where id = any(:ids) and type = 'region'"
        ),
        {"ids": ids},
    )
    return {rid: (name, lng, lat) for rid, name, lng, lat in rows.all()}


async def boundaries(
    db: AsyncSession, ids: list[uuid.UUID], tolerance: float
) -> list[tuple[uuid.UUID, str, str]]:
    """(id, name, simplified GeoJSON) of region outlines; ~100 m tolerance keeps Jawa Barat's
    27 regencies small enough for one request."""
    rows = await db.execute(
        text(
            "select id, value, ST_AsGeoJSON(ST_SimplifyPreserveTopology(boundary, :tol), 5) "
            "from reference_data where id = any(:ids) and type = 'region' "
            "and boundary is not null"
        ),
        {"ids": ids, "tol": tolerance},
    )
    return [(rid, name, geojson) for rid, name, geojson in rows.all()]


async def map_alert_threshold(db: AsyncSession, workspace_id: uuid.UUID) -> float:
    value = await db.scalar(
        text("select settings ->> 'map_alert_threshold' from workspaces where id = :ws"),
        {"ws": workspace_id},
    )
    try:
        threshold = float(value) if value is not None else 0.25
    except ValueError:
        return 0.25
    return threshold if 0 < threshold <= 1 else 0.25


# --- Field monitoring (Pantauan Lapangan, roadmap 5.2) ------------------------------------------


async def field_workers(
    db: AsyncSession, workspace_id: uuid.UUID, start: datetime, end: datetime, limit: int
) -> list[Any]:
    """Every active worker with their report count and newest report in the window. The point
    is left out for health structures, so a household is never placed on the map."""
    rows = await db.execute(
        text(
            "with latest as ("
            "  select distinct on (x.extension_worker_id) x.extension_worker_id as wid,"
            "  x.id, x.code, x.condition, x.received_at, x.accuracy_m, f.name as form_name,"
            "  x.region_id,"
            "  case when f.settings ->> 'sector_code' = 'health' then null else x.latitude end"
            "    as lat,"
            "  case when f.settings ->> 'sector_code' = 'health' then null else x.longitude end"
            "    as lng"
            "  from reports x join forms f on f.id = x.form_id"
            "  where x.workspace_id = :ws and x.received_at >= :start and x.received_at < :end"
            "  order by x.extension_worker_id, x.received_at desc, x.id desc),"
            " counts as (select extension_worker_id as wid, count(*) as n from reports"
            "  where workspace_id = :ws and received_at >= :start and received_at < :end"
            "  group by 1) "
            "select w.id, w.name, w.telegram_user_id is not null as telegram, wr.value as home,"
            " w.last_active_at, coalesce(c.n, 0) as reports,"
            " l.id as report_id, l.code, l.form_name, l.condition, l.received_at,"
            " lr.value as region, l.lat, l.lng, l.accuracy_m "
            "from extension_workers w"
            " left join latest l on l.wid = w.id"
            " left join counts c on c.wid = w.id"
            " left join reference_data wr on wr.id = w.region_id"
            " left join reference_data lr on lr.id = l.region_id "
            "where w.workspace_id = :ws and w.status = 'active' "
            "order by l.received_at desc nulls last, w.name limit :limit"
        ),
        {"ws": workspace_id, "start": start, "end": end, "limit": limit},
    )
    return list(rows.mappings().all())


async def field_cases(
    db: AsyncSession, workspace_id: uuid.UUID, start: datetime, end: datetime
) -> tuple[int, int, int, int]:
    """(attention or infected reports, infected reports, districts, regencies) in the window."""
    row = await db.execute(
        text(
            "select count(*) filter (where x.condition in ('attention', 'infected')),"
            " count(*) filter (where x.condition = 'infected'),"
            " count(distinct r.id) filter (where r.level = 'district'),"
            f" count(distinct {_REGENCY_ID}) "
            "from reports x left join reference_data r on r.id = x.region_id"
            " left join reference_data p on p.id = r.parent_id "
            "where x.workspace_id = :ws and x.received_at >= :start and x.received_at < :end"
        ),
        {"ws": workspace_id, "start": start, "end": end},
    )
    cases, infected, districts, regencies = row.one()
    return int(cases), int(infected), int(districts), int(regencies)


async def workers_reporting(
    db: AsyncSession, workspace_id: uuid.UUID, start: datetime, end: datetime
) -> int:
    value = await db.scalar(
        text(
            "select count(distinct x.extension_worker_id) from reports x"
            " join extension_workers w on w.id = x.extension_worker_id and w.status = 'active'"
            " where x.workspace_id = :ws and x.received_at >= :start and x.received_at < :end"
        ),
        {"ws": workspace_id, "start": start, "end": end},
    )
    return int(value or 0)
