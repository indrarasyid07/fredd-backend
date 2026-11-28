"""Aggregates for the dashboard. Every query is filtered by workspace and reads plain report
columns (copied once at creation), never the answers JSON. Days are counted in the workspace's
time zone; the caller passes the instants that bound them."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text
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
