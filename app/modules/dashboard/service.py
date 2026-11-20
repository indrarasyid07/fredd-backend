"""The dashboard summary (dashboard.md "Definisi angka"). KPIs, the 7-day chart and the
channel split ignore `range`; conditions and top regions follow it. Cached 15 seconds per
(workspace, range) in Redis: a new report shows within 15 seconds. Dropping the cache on
`report.created` comes with the event stream (roadmap 6.1), the module that publishes it."""

import logging
import uuid
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis
from app.core.time import now_utc
from app.modules.dashboard import repository
from app.modules.dashboard.schemas import (
    ChannelShareOut,
    CompletionOut,
    ConditionCountOut,
    ConditionsOut,
    DashboardRange,
    DashboardSummaryOut,
    DayCountOut,
    KpisOut,
    MonitoredLandOut,
    RegionCountOut,
    ReportsTodayOut,
    SetupOut,
    WorkersKpiOut,
)
from app.modules.workspaces import service as workspaces

logger = logging.getLogger(__name__)

CACHE_SECONDS = 15
CONDITIONS = ("healthy", "attention", "infected")
RANGE_DAYS = {"today": 1, "7d": 7, "30d": 30}
LAND_DAYS = 30


def _cache_key(workspace_id: uuid.UUID, range_: str) -> str:
    return f"dashboard:summary:{workspace_id}:{range_}"


async def forget(workspace_id: uuid.UUID) -> None:
    """Drop the cached summaries after a new report (Redis down: they expire on their own)."""
    try:
        await redis.delete(*(_cache_key(workspace_id, r) for r in RANGE_DAYS))
    except RedisError:
        logger.warning("dashboard cache not cleared: redis unavailable")


async def summary(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    range_: DashboardRange = "today",
    *,
    now: datetime | None = None,
) -> DashboardSummaryOut:
    if now is None:
        cached = await _cached(workspace_id, range_)
        if cached is not None:
            return cached
    result = await _compute(db, workspace_id, range_, now or now_utc())
    if now is None:
        try:
            await redis.set(
                _cache_key(workspace_id, range_), result.model_dump_json(), ex=CACHE_SECONDS
            )
        except RedisError:
            logger.warning("dashboard cache not stored: redis unavailable")
    return result


async def _cached(workspace_id: uuid.UUID, range_: str) -> DashboardSummaryOut | None:
    try:
        raw = await redis.get(_cache_key(workspace_id, range_))
    except RedisError:
        return None
    return DashboardSummaryOut.model_validate_json(raw) if raw else None


async def _compute(
    db: AsyncSession, workspace_id: uuid.UUID, range_: DashboardRange, now: datetime
) -> DashboardSummaryOut:
    tz_name = await workspaces.get_timezone_name(db, workspace_id)
    tz = ZoneInfo(tz_name)
    local_now = now.astimezone(tz)
    today = datetime.combine(local_now.date(), datetime.min.time(), tz)
    day = timedelta(days=1)

    value = await repository.count_between(db, workspace_id, today, now)
    yesterday = await repository.count_between(db, workspace_id, today - day, now - day)

    week_start = today - 6 * day
    per_day = await repository.count_per_day(db, workspace_id, tz_name, week_start - 7 * day, now)
    dates = [(today - (6 - i) * day).date() for i in range(7)]
    previous_dates = [d - timedelta(days=7) for d in dates]
    daily = [DayCountOut(date=d, count=per_day.get(d, 0)) for d in dates]
    previous = [DayCountOut(date=d, count=per_day.get(d, 0)) for d in previous_dates]

    channels = await repository.count_per_channel(db, workspace_id, week_start, now)
    whatsapp, telegram = largest_remainder(
        [channels.get("whatsapp", 0), channels.get("telegram", 0)]
    )

    total_workers, active_workers = await repository.worker_counts(db, workspace_id, today, now)
    area, points, regencies = await repository.monitored_land(
        db, workspace_id, today - (LAND_DAYS - 1) * day, now
    )
    complete, reports_today = await repository.completion(db, workspace_id, today, now)

    range_start = today - (RANGE_DAYS[range_] - 1) * day
    by_condition = await repository.count_per_condition(db, workspace_id, range_start, now)
    counts = [by_condition.get(c, 0) for c in CONDITIONS]
    percents = largest_remainder(counts)
    infected = await repository.top_regencies(
        db, workspace_id, range_start, now, condition="infected", limit=2
    )
    top = await repository.top_regencies(
        db, workspace_id, range_start, now, condition=None, limit=3
    )
    form_created, has_workers, has_reports = await repository.setup_flags(db, workspace_id)

    return DashboardSummaryOut(
        as_of=local_now,
        timezone=tz_name,
        kpis=KpisOut(
            reports_today=ReportsTodayOut(
                value=value,
                yesterday_same_time=yesterday,
                delta_pct=_delta(value, yesterday),
                trend=[d.count for d in daily],
            ),
            workers=WorkersKpiOut(
                active=active_workers,
                total=total_workers,
                not_reported=total_workers - active_workers,
            ),
            monitored_land=MonitoredLandOut(
                area_ha=float(area.quantize(Decimal("0.1"))), points=points, regencies=regencies
            ),
            completion=CompletionOut(
                percent=round(complete * 100 / reports_today) if reports_today else None,
                blurry_rejected=0,
            ),
        ),
        daily=daily,
        previous_daily=previous,
        channels=ChannelShareOut(whatsapp=whatsapp, telegram=telegram),
        conditions=ConditionsOut(
            range=range_,
            total=sum(counts),
            items=[
                ConditionCountOut(key=key, count=n, percent=p)
                for key, n, p in zip(CONDITIONS, counts, percents, strict=True)
            ],
            unknown=by_condition.get(None, 0),
            top_infected_regions=[_region(r) for r in infected],
        ),
        top_regions=[_region(r) for r in top],
        setup=SetupOut(
            form_created=form_created, channel_and_worker=has_workers, has_reports=has_reports
        ),
    )


def _delta(today: int, yesterday: int) -> float | None:
    if yesterday == 0:
        return None
    change = Decimal(today - yesterday) * 100 / Decimal(yesterday)
    return float(change.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def largest_remainder(counts: list[int]) -> list[int]:
    """Whole percents adding up to exactly 100 (all 0 when every count is 0)."""
    total = sum(counts)
    if total == 0:
        return [0] * len(counts)
    exact = [n * 100 / total for n in counts]
    floors = [int(x) for x in exact]
    by_remainder = sorted(range(len(counts)), key=lambda i: exact[i] - floors[i], reverse=True)
    for i in by_remainder[: 100 - sum(floors)]:
        floors[i] += 1
    return floors


def _region(row: tuple[uuid.UUID, str, int]) -> RegionCountOut:
    region_id, name, count = row
    return RegionCountOut(region_id=region_id, name=name, count=count)
