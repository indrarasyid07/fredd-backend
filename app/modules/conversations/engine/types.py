"""What the engine reads and returns. Channel-neutral: adapters turn Telegram/WhatsApp updates
into `Inbound` and `Outbound` into API calls. State is plain JSON so it can live in
`conversations.step` / `draft_answers` and survive restarts."""

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.modules.forms.schemas import FormDefinition

Status = Literal[
    "idle",
    "joining",
    "identifying",
    "choosing_form",
    "asking",
    "confirming_summary",
    "submitted",
    "needs_help",
    "taken_over",
]
MediaKind = Literal["photo", "video", "voice", "document"]


# --- In -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Location:
    lat: float
    lng: float
    accuracy_m: float | None = None


@dataclass(frozen=True)
class Media:
    kind: MediaKind
    # Where the worker stored it (object key); the engine only keeps the reference.
    ref: str
    # Telegram album id: photos sent together share it (photo before "mulai", roadmap 3.8).
    group: str | None = None


@dataclass(frozen=True)
class Inbound:
    """One message from the extension worker: typed text, a tapped button (`button` carries the
    button's value), a shared location, or a media file."""

    text: str | None = None
    button: str | None = None
    location: Location | None = None
    media: Media | None = None
    # `text` is the transcript of a voice note (roadmap 12.3); `audio` is where it is stored.
    spoken: bool = False
    audio: str | None = None
    # A language model's rewrite of `text` for the open question (roadmap 12.7), set by the
    # service after `Step.unread`. Read with the same rules and always confirmed, never saved
    # silently.
    ai_text: str | None = None
    # A language model's reading of a voice-mode sentence (Voice Lab, after `Step.unread_voice`)
    # or of a photo (after `Step.read_photo`): field key → the value, rewritten for the parsers.
    # Each value is read with the same rules and confirmed by the worker before it is kept.
    ai_values: Mapping[str, str] | None = None


# --- Out ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Button:
    label: str
    value: str


@dataclass(frozen=True)
class Outbound:
    """One message to send. `*bold*` marks recorded values; adapters render it per channel."""

    text: str
    buttons: tuple[Button, ...] = ()
    # The channel should offer its "share location" button.
    ask_location: bool = False


@dataclass(frozen=True)
class ClaimCode:
    """Text looks like a join code: the service checks it and binds the chat (roadmap 3.6)."""

    code: str


@dataclass(frozen=True)
class SelectTopic:
    """The worker picked one of their topics: the service loads its form and calls `start`."""

    topic_id: str


@dataclass(frozen=True)
class SubmitReport:
    """All answers confirmed: the service creates the report in the same transaction as
    `status = submitted`, then sends `report_saved(code)`."""

    answers: dict[str, Any]
    needs_review: bool
    review_reasons: tuple[str, ...]
    # Voice Lab (roadmap 12.3): transcript, audio, and per field the words heard and confidence.
    voice: dict[str, Any] | None = None


@dataclass(frozen=True)
class NeedsHelp:
    """Hand the conversation to an admin (Aktivitas Agent queue)."""

    reason: Literal["failed_attempts", "asked_for_help"]
    field: str | None


Effect = ClaimCode | SelectTopic | SubmitReport | NeedsHelp


# --- Context and state --------------------------------------------------------------------------


@dataclass(frozen=True)
class Topic:
    """A structure the worker is bound to: shown as "Organisasi · Struktur"."""

    id: str
    label: str


AgentStyle = Literal["friendly", "formal", "brief"]


@dataclass(frozen=True)
class AgentVoice:
    """How the organization's agent speaks (Pengaturan agent): its name, the greeting sent once
    a worker has joined (None = the default for the style), and the style of the opening and
    closing lines. The questions themselves always come from the form."""

    name: str = "Fluctuz"
    style: AgentStyle = "friendly"
    greeting: str | None = None


@dataclass(frozen=True)
class EngineContext:
    """Everything the engine needs from the database, loaded by the service per message."""

    # How Fluctuz addresses the worker: "Pak Budi", "Bu Sari", "Kak Rina".
    salutation: str
    today: dt.date
    topics: Sequence[Topic] = ()
    # The form of the active topic (the conversation's form_version).
    definition: FormDefinition | None = None
    topic_label: str = ""
    # Extra unit aliases from reference data (alias → unit code).
    units: Mapping[str, str] = field(default_factory=dict)
    # The topic's structure is in voice mode (Voice Lab, roadmap 12.3): one message, many fields.
    voice_mode: bool = False
    agent: AgentVoice = field(default_factory=AgentVoice)


@dataclass
class ConversationState:
    status: Status = "idle"
    topic_id: str | None = None
    # Key of the field being asked (conversations.step).
    step: str | None = None
    answers: dict[str, Any] = field(default_factory=dict)
    # Fields made required by rules, and why the report needs review.
    required_by_rules: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    failed_attempts: int = 0
    # A guessed value waiting for "Ya" (field, value, how it is shown).
    pending: dict[str, Any] | None = None
    # Values a language model read from a Voice Lab sentence or a photo, by field key ({value,
    # display}); each becomes a "Ya / Ubah" confirmation when the bot reaches its field.
    ai_suggested: dict[str, Any] = field(default_factory=dict)
    # Back to the summary after re-answering one field.
    editing: bool = False
    # Photos sent before a topic was chosen, used once the report starts; and the album they
    # came in, so the rest of that album joins them (conversation-engine.md "Foto sebelum mulai").
    held_media: list[str] = field(default_factory=list)
    media_group: str | None = None
    # Voice Lab: what the sentence that filled the report was (see SubmitReport.voice).
    voice: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_json(cls, data: Mapping[str, Any] | None) -> ConversationState:
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


@dataclass(frozen=True)
class Step:
    """The engine's answer to one message."""

    state: ConversationState
    replies: tuple[Outbound, ...] = ()
    effects: tuple[Effect, ...] = ()
    # Key of the open field whose typed answer the parsers could not read: the service may ask
    # a language model and run the message again with `Inbound.ai_text`.
    unread: str | None = None
    # Voice Lab: keys of the spoken fields a voice-mode sentence did not fill for sure. The
    # service may ask a language model and run the message again with `Inbound.ai_values`.
    unread_voice: tuple[str, ...] = ()
    # "Baca struk dan foto": a photo the service may have read by a language model for the
    # fields in `read_keys`, then run the message again with `Inbound.ai_values`.
    read_photo: str | None = None
    read_keys: tuple[str, ...] = ()
