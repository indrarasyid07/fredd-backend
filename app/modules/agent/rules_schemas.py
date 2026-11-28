"""Aturan ambil alih (roadmap 6.7): IF something happens in a chat, THEN hand it to an admin or
raise an alert. Stored per organization in `workspaces.settings["agent_rules"]`."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_RULES = 20


class KeywordTrigger(BaseModel):
    """The worker's message contains one of these words or phrases (whole words, any case)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["keyword"] = "keyword"
    keywords: list[Annotated[str, Field(min_length=2, max_length=40)]] = Field(
        min_length=1, max_length=20
    )

    @field_validator("keywords")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        cleaned = [" ".join(k.lower().split()) for k in value]
        return list(dict.fromkeys(k for k in cleaned if k))


class BlurryPhotoTrigger(BaseModel):
    """Blurry photos in a row. Needs blur scores (roadmap 5.1): stored, not yet evaluated."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["blurry_photo"] = "blurry_photo"
    times: int = Field(default=3, ge=2, le=10)


class ConditionTrigger(BaseModel):
    """A report is submitted with this condition."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["condition"] = "condition"
    equals: Literal["attention", "infected"] = "infected"


class NoReplyTrigger(BaseModel):
    """No reply this many hours after the second draft reminder (roadmap 7.1)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["no_reply"] = "no_reply"
    hours: int = Field(default=3, ge=1, le=48)


Trigger = Annotated[
    KeywordTrigger | BlurryPhotoTrigger | ConditionTrigger | NoReplyTrigger,
    Field(discriminator="type"),
]


class EscalationRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=60)
    enabled: bool = False
    trigger: Trigger
    # handover: the conversation goes to "Perlu ambil alih" (needs_help); notify: an alert in
    # the activity log only, the bot carries on.
    action: Literal["handover", "notify"] = "handover"
    priority: Literal["normal", "urgent"] = "normal"

    @model_validator(mode="after")
    def _action_fits(self) -> EscalationRule:
        if self.trigger.type == "condition" and self.action != "notify":
            raise ValueError("Laporan yang sudah terkirim hanya bisa memicu notifikasi.")
        return self


class EscalationRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: list[EscalationRule] = Field(max_length=MAX_RULES)

    @model_validator(mode="after")
    def _unique_ids(self) -> EscalationRules:
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Setiap aturan harus punya id yang berbeda.")
        return self


class EscalationRulesOut(EscalationRules):
    # When an admin last saved them; null while the organization uses the suggested rules.
    updated_at: datetime | None = None
    # Triggers the platform can evaluate today; blurry_photo waits for blur scores (5.1).
    available_triggers: list[str]


def suggested_rules() -> list[EscalationRule]:
    """The four rules of the design, all off: nothing changes until an admin turns one on."""
    return [
        EscalationRule(
            id="ask-for-person",
            name="Penyuluh minta bicara dengan petugas",
            trigger=KeywordTrigger(keywords=["petugas", "admin", "bicara dengan orang", "manusia"]),
            action="handover",
        ),
        EscalationRule(
            id="blurry-photos",
            name="Foto buram berulang",
            trigger=BlurryPhotoTrigger(times=3),
            action="handover",
            priority="urgent",
        ),
        EscalationRule(
            id="infected-report",
            name="Laporan ditandai terserang",
            trigger=ConditionTrigger(equals="infected"),
            action="notify",
            priority="urgent",
        ),
        EscalationRule(
            id="no-reply",
            name="Penyuluh tidak membalas",
            trigger=NoReplyTrigger(hours=3),
            action="handover",
        ),
    ]
