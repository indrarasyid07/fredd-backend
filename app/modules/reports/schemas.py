import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Condition = Literal["healthy", "attention", "infected"]
# "unknown" = reports without a condition (structure without a `condition` field, or skipped).
ConditionFilter = Literal["healthy", "attention", "infected", "unknown"]
Channel = Literal["telegram", "whatsapp"]


class NamedRef(BaseModel):
    id: uuid.UUID
    name: str


class ReportListItemOut(BaseModel):
    """One row of a report list (dashboard "Laporan terbaru", activity feed, tables)."""

    id: uuid.UUID
    code: str
    form: NamedRef
    worker: NamedRef
    channel: Channel
    region: NamedRef | None
    condition: Condition | None
    area_ha: float | None
    photo_count: int
    needs_review: bool
    complete: bool
    received_at: datetime
    # Voice Lab: what was said, for reports filled from a voice note; null otherwise.
    transcript: str | None = None
    # A supervisor verified the values (roadmap 12.5).
    verified: bool = False


class ReportFieldOut(BaseModel):
    """One answer, labelled by the structure version the report was made with."""

    key: str
    label: str
    type: str
    # The stored answer (decimal string, ISO date, option value, list, {lat, lng}...); null
    # when skipped.
    value: Any
    # How it reads in Indonesian ("1,5 ha", "Padi", "Dilewati").
    display: str
    unit: str | None = None


class ReportPhotoOut(BaseModel):
    id: uuid.UUID
    field_key: str
    position: int
    # Signed link, valid until `expires_at`; null while the file is not in Fluctuz storage.
    url: str | None
    expires_at: datetime | None
    # A vision model's note for reviewers (roadmap 12.7): what the photo shows, and a
    # "Perlu dicek (…)" prefix when it is blurry, dark, off topic or contradicts the answers.
    # Advice only; null until checked, or when the check is off or failed.
    ai_note: str | None = None


class ReportLocationOut(BaseModel):
    lat: float
    lng: float
    accuracy_m: float | None


class ReportReviewOut(BaseModel):
    needs_review: bool
    # Why, in Indonesian ("Luas lahan di atas 50 ha").
    reasons: list[str]


class VoiceFieldOut(BaseModel):
    key: str
    label: str
    # The words this value was read from, and how sure Fluctuz was (0–1).
    heard: str
    confidence: float
    confident: bool


class ReportVoiceOut(BaseModel):
    """The voice note that filled the report (Voice Lab, roadmap 12.3/12.4)."""

    transcript: str
    # Signed link to the recording, valid until `audio_expires_at`; null when not served.
    audio_url: str | None
    audio_expires_at: datetime | None
    fields: list[VoiceFieldOut]


class ReportVerificationOut(BaseModel):
    verified: bool
    verified_at: datetime | None
    # Name of the supervisor; null if not verified or the account is gone.
    verified_by: str | None


class ReportCorrectionOut(BaseModel):
    field_key: str
    label: str
    old_display: str
    new_display: str
    reason: str
    by: str | None
    at: datetime


class CorrectValueRequest(BaseModel):
    field_key: str = Field(min_length=1, max_length=64)
    # The right value as the supervisor types it ("26 derajat", "Lolos", "S-2042").
    value: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=3, max_length=500)


class ReportFormOut(NamedRef):
    version: int


class ReportDetailOut(BaseModel):
    id: uuid.UUID
    code: str
    form: ReportFormOut
    worker: NamedRef
    channel: Channel
    received_at: datetime
    location: ReportLocationOut | None
    region: NamedRef | None
    condition: Condition | None
    area_ha: float | None
    complete: bool
    fields: list[ReportFieldOut]
    photos: list[ReportPhotoOut]
    review: ReportReviewOut
    voice: ReportVoiceOut | None = None
    verification: ReportVerificationOut
    corrections: list[ReportCorrectionOut]


class VoiceSummaryOut(BaseModel):
    """Counts behind the Voice page and an analyst's profile (roadmap 12.4). Days and months
    follow the workspace time zone; the client only formats these numbers (B-044)."""

    # Every voice report, and how many still wait for a supervisor.
    total: int
    pending: int
    verified: int
    today: int
    yesterday: int
    today_telegram: int
    today_whatsapp: int
    this_month: int
    last_month: int
    # Mean confidence (0–1) of every value read from speech in the last 7 days; null if none.
    confidence_7d: float | None
    # Last 30 days: share (0–1) of voice reports with at least one correction; null if none.
    corrected_share_30d: float | None
    # Label of the field corrected most often in the last 30 days; null if none.
    most_corrected: str | None


# --- Report downloads (roadmap 5.4) -------------------------------------------------------------

ExportSpan = Literal["today", "7d", "30d", "custom"]
ReportExportFormat = Literal["pdf", "xlsx", "csv"]
ReportExportStatus = Literal["queued", "running", "done", "failed", "expired"]


class ExportRange(BaseModel):
    """`today`, the last 7 or 30 days including today, or `custom` from/to (local dates in the
    workspace time zone, both inclusive, at most 366 days)."""

    model_config = {"populate_by_name": True}

    type: ExportSpan
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None


class ExportInclude(BaseModel):
    # Map: PDF only. Photos: Excel adds a photo count column; CSV refuses both.
    map: bool = False
    photos: bool = False
    # Coordinates, GPS accuracy and location answers.
    gps: bool = True


class CreateExportRequest(BaseModel):
    format: ReportExportFormat
    range: ExportRange
    # Required for CSV (one structure, one set of columns); Excel writes one sheet per structure.
    form_id: uuid.UUID | None = None
    region_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    conditions: list[ConditionFilter] = Field(default_factory=list, max_length=4)
    include: ExportInclude = Field(default_factory=ExportInclude)
    # Needs a field role marking people's names (Domain 2); refused until then.
    anonymize_farmers: bool = False


class ReportExportOut(BaseModel):
    id: uuid.UUID
    status: ReportExportStatus
    format: ReportExportFormat
    row_count: int | None
    filename: str | None
    # Why it failed, in Indonesian; null otherwise.
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    # The file is deleted then (7 days after it was written).
    expires_at: datetime | None


class ReportCountOut(BaseModel):
    count: int
