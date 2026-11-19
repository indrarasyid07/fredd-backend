from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.join_codes.constants import ApprovalMode, JoinCodeStatus


class JoinCodeOut(BaseModel):
    # Display form, e.g. K7M2-9QXA.
    code: str
    status: JoinCodeStatus
    approval_mode: ApprovalMode
    expires_at: datetime | None
    max_uses: int | None
    use_count: int
    # True when people can join with it now: code active and the structure pilot or active.
    claimable: bool
    # Deep links into the shared bots with the code filled in; null when the bot is not set up.
    whatsapp_url: str | None
    telegram_url: str | None


class UpdateJoinCodeRequest(BaseModel):
    """Only the fields sent change. `max_uses: null` removes the limit."""

    model_config = ConfigDict(extra="forbid")

    # Revoking happens by rotating the code (roadmap 3.10), not here.
    status: Literal["active", "paused"] | None = None
    approval_mode: ApprovalMode | None = None
    expires_at: datetime | None = None
    max_uses: int | None = Field(default=None, gt=0, le=100_000)
