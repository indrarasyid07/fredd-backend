import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

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
