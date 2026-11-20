import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

DashboardRange = Literal["today", "7d", "30d"]


class ReportsTodayOut(BaseModel):
    value: int
    yesterday_same_time: int
    # (today − yesterday until the same hour) ÷ yesterday × 100, one decimal; null when 0.
    delta_pct: float | None
    # Reports per day for the last 7 days, oldest first, today last.
    trend: list[int]


class WorkersKpiOut(BaseModel):
    active: int  # active workers with a report today
    total: int  # active workers
    not_reported: int


class MonitoredLandOut(BaseModel):
    area_ha: float
    points: int
    regencies: int


class CompletionOut(BaseModel):
    # Today's reports with every required field ÷ today's reports × 100; null without reports.
    percent: int | None
    # Photos refused as blurry today (blur scoring comes with roadmap 5.1; 0 until then).
    blurry_rejected: int


class KpisOut(BaseModel):
    reports_today: ReportsTodayOut
    workers: WorkersKpiOut
    monitored_land: MonitoredLandOut
    completion: CompletionOut


class DayCountOut(BaseModel):
    date: date
    count: int


class ConditionCountOut(BaseModel):
    key: Literal["healthy", "attention", "infected"]
    count: int
    # Rounded by largest remainder so the three add up to 100 (0 each without reports).
    percent: int


class RegionCountOut(BaseModel):
    region_id: uuid.UUID
    name: str
    count: int


class ConditionsOut(BaseModel):
    range: DashboardRange
    total: int  # reports with a known condition
    items: list[ConditionCountOut]
    unknown: int  # reports without a condition
    top_infected_regions: list[RegionCountOut]


class ChannelShareOut(BaseModel):
    """Share of the 7-day reports by channel, in percent (adds up to 100, or 0 and 0)."""

    whatsapp: int
    telegram: int


class SetupOut(BaseModel):
    form_created: bool
    channel_and_worker: bool
    has_reports: bool


class DashboardSummaryOut(BaseModel):
    as_of: datetime
    timezone: str
    kpis: KpisOut
    # Always 7 days, oldest first, today last (days without reports are 0).
    daily: list[DayCountOut]
    # The 7 days before `daily`, same order (the dashed comparison line).
    previous_daily: list[DayCountOut]
    channels: ChannelShareOut
    conditions: ConditionsOut
    top_regions: list[RegionCountOut]
    setup: SetupOut
