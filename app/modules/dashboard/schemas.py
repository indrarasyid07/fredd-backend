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


class HourlyOut(BaseModel):
    """Reports per local hour (24 entries, 0 = midnight) for yesterday and today so far."""

    yesterday: list[int]
    today: list[int]


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
    # The busiest-hours heatmap of "Laporan masuk".
    hourly: HourlyOut
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
    # From the wizard's template (form settings): picks the sector layout (roadmap 11.3a).
    sector_code: str | None = None
    template_code: str | None = None
    # The current version has a location field: the dashboard may show a map.
    has_location: bool = False


class FormKpisOut(BaseModel):
    """The structure's headline numbers over the range (roadmap 11.3a)."""

    # Reports in the same span just before, up to the same time of day.
    previous_total: int
    delta_pct: float | None
    # Workers with at least one report of this structure in the range.
    workers_reporting: int
    complete_percent: int | None
    needs_review: int


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
    kpis: FormKpisOut | None = None


# --- Map (roadmap 5.2) ---------------------------------------------------------------------------


class MapValueOut(BaseModel):
    """One value of the field that colours the map, with its count in the range."""

    value: str  # option value, or "unknown" (no answer)
    label: str
    count: int


class MapColorFieldOut(BaseModel):
    # "condition" for the crop condition (alert threshold), "choice" for any other single choice.
    kind: Literal["condition", "choice"]
    key: str
    label: str
    values: list[MapValueOut]


class MapRegionOut(BaseModel):
    region_id: uuid.UUID  # a regency
    name: str
    centroid: list[float] | None  # [lng, lat]
    count: int
    by_value: dict[str, int]
    # The value the region is drawn with: the alert colour for conditions, else the most common.
    color: str
    latest_report_id: uuid.UUID | None


class MapPointOut(BaseModel):
    id: uuid.UUID
    lat: float
    lng: float
    value: str | None
    # GPS accuracy unknown or worse than 50 m: drawn hollow, "akurasi tidak pasti".
    approximate: bool


class ReportMapOut(BaseModel):
    range: DashboardRange
    total: int  # reports in the range (after filters)
    located: int  # of which with coordinates
    color_field: MapColorFieldOut | None
    regions: list[MapRegionOut]
    points: list[MapPointOut]  # newest first, at most 2.000
    truncated: bool
    # "regions_only": a health structure; no points, regions under 5 reports left out.
    privacy: Literal["full", "regions_only"]
    hidden_regions: int


class BoundaryFeatureOut(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: uuid.UUID
    properties: dict[str, str]
    geometry: dict[str, object]


class BoundariesOut(BaseModel):
    """Simplified regency outlines as a GeoJSON FeatureCollection, for the map's region layer."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[BoundaryFeatureOut]
