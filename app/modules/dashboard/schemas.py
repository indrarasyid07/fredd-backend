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


# --- One structure's widgets (roadmap 4.7, D17) -------------------------------------------------


class ChoiceStatOut(BaseModel):
    value: str
    label: str
    count: int
    # Single choice: share of the answers, adding up to 100. Multiple choice: share of the
    # reports that answered (they may pick several, so these do not add up to 100).
    percent: int


class NumberStatOut(BaseModel):
    count: int
    sum: float
    avg: float
    min: float
    max: float


class FieldStatOut(BaseModel):
    """One choice or number field of the structure and what its answers add up to."""

    key: str
    label: str
    type: Literal["single_choice", "multi_choice", "number"]
    role: str | None
    unit: str | None
    answered: int  # reports in the range with an answer
    choices: list[ChoiceStatOut] | None = None  # choice fields
    numbers: NumberStatOut | None = None  # number fields (null without answers)


class FormRefOut(BaseModel):
    id: uuid.UUID
    name: str
    version: int


class FormDashboardOut(BaseModel):
    """Data for generic widgets of one structure: counts, trend, and every choice and number
    field in the order of its current version."""

    as_of: datetime
    timezone: str
    range: DashboardRange
    form: FormRefOut
    total: int  # reports in the range
    daily: list[DayCountOut]  # last 7 days, today last (ignores `range`)
    fields: list[FieldStatOut]
    top_regions: list[RegionCountOut]
