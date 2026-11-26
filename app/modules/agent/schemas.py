"""Pengaturan agent: how an organization's agent speaks and what it may do on its own."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.conversations.engine.types import AgentStyle

MAX_TEST_MESSAGES = 40


class AgentSettings(BaseModel):
    """What an admin edits. Stored in `workspaces.settings["agent"]`."""

    model_config = ConfigDict(extra="forbid")

    # Shown when the agent introduces itself ("Saya Fluctuz, ...").
    name: str = Field(default="Fluctuz", min_length=1, max_length=40)
    # friendly (Ramah), formal (Formal), brief (Singkat): the opening and closing lines.
    style: AgentStyle = "friendly"
    # Sent once a worker has joined; null = the default greeting for the style.
    greeting: str | None = Field(default=None, max_length=200)
    # Voice notes are transcribed and report photos get an AI note (roadmap 12.7).
    voice_and_photos: bool = True
    # Answers the rules cannot read are read by a language model, then confirmed.
    read_free_answers: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Nama agent wajib diisi.")
        return value

    @field_validator("greeting")
    @classmethod
    def _greeting(cls, value: str | None) -> str | None:
        value = " ".join(value.split()) if value else None
        return value or None


class AgentSettingsOut(AgentSettings):
    # When an admin last saved them; null while the organization uses the defaults.
    updated_at: datetime | None = None
    # Whether the platform can do the AI parts at all (an OpenAI key on the server). When false
    # the two AI switches are stored but have no effect.
    ai_available: bool = False
    voice_available: bool = False


class AgentPreviewOut(BaseModel):
    """The lines the settings change, for the preview next to the form."""

    after_join: str
    report_start: str
    # The report's opening line alone, without the first question (the wizard adds its own).
    report_opening: str
    report_saved: str


# --- Test chat ----------------------------------------------------------------------------------


class ChatInput(BaseModel):
    """One message of the admin's test chat: typed text or a tapped button's value."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=500)
    button: str | None = Field(default=None, max_length=100)
    # The language model's reading returned for this message earlier; replays reuse it instead
    # of asking again.
    ai_text: str | None = Field(default=None, max_length=200)


class AgentTestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    form_id: uuid.UUID
    # The settings to try (usually unsaved edits).
    settings: AgentSettings
    # The whole test chat so far, oldest first; the server replays it every time.
    messages: list[ChatInput] = Field(default_factory=list, max_length=MAX_TEST_MESSAGES)


class ChatButtonOut(BaseModel):
    label: str
    value: str


class ChatReplyOut(BaseModel):
    text: str
    buttons: list[ChatButtonOut]


class ChatTurnOut(BaseModel):
    # Index into `messages`; null for the greeting before the first message.
    message: int | None
    replies: list[ChatReplyOut]
    # What happened besides the replies, for the admin ("Jawaban dibaca AI sebagai 0,5").
    events: list[str]
    # The language model's reading of this message, to send back as `ai_text` next time.
    ai_text: str | None = None


class AgentTestOut(BaseModel):
    form_name: str
    turns: list[ChatTurnOut]
    status: Literal["idle", "asking", "confirming_summary", "submitted", "needs_help", "other"]
