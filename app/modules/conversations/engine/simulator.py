"""Run the engine without a database or a channel: for tests now and the chat simulator later
(roadmap 3.9). `FakeChannel` records what would be sent; `Simulator` plays the service's part
for the effects (join codes, topic choice, saving the report) with in-memory data."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from app.modules.conversations.engine import machine
from app.modules.conversations.engine.types import (
    ClaimCode,
    ConversationState,
    Effect,
    EngineContext,
    Inbound,
    Location,
    Media,
    NeedsHelp,
    Outbound,
    SelectTopic,
    Step,
    SubmitReport,
    Topic,
)
from app.modules.forms.schemas import FormDefinition


@dataclass
class FakeChannel:
    """Collects outgoing messages in order, like a chat window."""

    sent: list[Outbound] = field(default_factory=list)

    def send(self, message: Outbound) -> None:
        self.sent.append(message)

    @property
    def last(self) -> Outbound:
        return self.sent[-1]

    def texts(self) -> list[str]:
        return [m.text for m in self.sent]


@dataclass
class SimTopic:
    id: str
    label: str
    definition: FormDefinition
    code: str  # join code without the dash


@dataclass
class Simulator:
    """One extension worker chatting with Fluctuz."""

    topics: list[SimTopic]
    salutation: str = "Pak Budi"
    today: dt.date = dt.date(2026, 11, 19)
    channel: FakeChannel = field(default_factory=FakeChannel)
    state: ConversationState = field(default_factory=ConversationState)
    bound: list[str] = field(default_factory=list)
    reports: list[dict[str, Any]] = field(default_factory=list)
    help_requests: list[NeedsHelp] = field(default_factory=list)

    # --- what the worker does -------------------------------------------------------------------

    def say(self, text: str) -> list[Outbound]:
        return self._receive(Inbound(text=text))

    def tap(self, value: str) -> list[Outbound]:
        return self._receive(Inbound(button=value))

    def share_location(
        self, lat: float, lng: float, accuracy_m: float | None = 10
    ) -> list[Outbound]:
        return self._receive(Inbound(location=Location(lat, lng, accuracy_m)))

    def send_media(self, kind: Any, ref: str) -> list[Outbound]:
        return self._receive(Inbound(media=Media(kind, ref)))

    # --- the service's part ---------------------------------------------------------------------

    def _context(self) -> EngineContext:
        mine = [t for t in self.topics if t.id in self.bound]
        active = next((t for t in mine if t.id == self.state.topic_id), None)
        return EngineContext(
            salutation=self.salutation,
            today=self.today,
            topics=[Topic(t.id, t.label) for t in mine],
            definition=active.definition if active else None,
            topic_label=active.label if active else "",
        )

    def _receive(self, message: Inbound) -> list[Outbound]:
        before = len(self.channel.sent)
        self._apply(machine.handle(self.state, message, self._context()))
        return self.channel.sent[before:]

    def _apply(self, step: Step) -> None:
        self.state = step.state
        for reply in step.replies:
            self.channel.send(reply)
        for effect in step.effects:
            self._effect(effect)

    def _effect(self, effect: Effect) -> None:
        if isinstance(effect, ClaimCode):
            topic = next((t for t in self.topics if t.code == effect.code), None)
            if topic is None:
                self.channel.send(Outbound("Kode tidak dikenali."))
                return  # the report in progress, if any, carries on
            if topic.id not in self.bound:
                self.bound.append(topic.id)
            self.state = ConversationState(topic_id=topic.id)
            self._apply(machine.start(self.state, self._context()))
        elif isinstance(effect, SelectTopic):
            self.state.topic_id = effect.topic_id
            self._apply(machine.start(self.state, self._context()))
        elif isinstance(effect, SubmitReport):
            code = f"LP-2611-{len(self.reports) + 1:04d}"
            self.reports.append(
                {
                    "code": code,
                    "topic_id": self.state.topic_id,
                    "answers": effect.answers,
                    "needs_review": effect.needs_review,
                    "review_reasons": effect.review_reasons,
                }
            )
            self.channel.send(machine.report_saved(code, self._context()))
        elif isinstance(effect, NeedsHelp):
            self.help_requests.append(effect)
