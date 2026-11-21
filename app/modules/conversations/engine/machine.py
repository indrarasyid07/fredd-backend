"""The conversation state machine (conversation-engine.md). Pure: `handle(state, message, ctx)`
returns the next state, the replies and the effects; it never touches the database or a channel.

    idle ─(join code)→ joining ─→ identifying ─(several topics)→ choosing_form
                                       └────────────(one topic)→ asking(step) ⇄ confirm a guess
    asking ─(all answered)→ confirming_summary ─(Kirim)→ submitted
       └─(3 failures)→ offer Lewati / Minta bantuan → needs_help          taken_over: silent

Answers are stored as JSON: numbers as decimal strings, dates as ISO strings, choices as their
value, several choices as a list, a location as {lat, lng, accuracy_m} or {name}, media as a list
of stored references, a skipped optional field as null.
"""

import datetime as dt
import re
from dataclasses import replace
from decimal import Decimal
from typing import Any

from app.modules.ai.extraction import CONFIDENT, extract
from app.modules.conversations.engine import copy
from app.modules.conversations.engine.parsers import (
    DEFAULT_UNITS,
    Choice,
    normalize,
    parse_choice,
    parse_date,
    parse_multi_choice,
    parse_number,
    parse_yes_no,
)
from app.modules.conversations.engine.types import (
    Button,
    ClaimCode,
    ConversationState,
    EngineContext,
    Inbound,
    NeedsHelp,
    Outbound,
    SelectTopic,
    Step,
    SubmitReport,
)
from app.modules.forms.constants import SPOKEN_TYPES
from app.modules.forms.schemas import FieldDefinition, FormDefinition

MAX_FAILURES = 3
# More options than this are typed, not tapped (conversation-engine.md "Pilihan jawaban").
MAX_BUTTONS = 10

_START = {"mulai", "/mulai", "/start", "start", "lapor", "laporan baru", "halo", "hai"}
_RESUME = {"lanjut", "/lanjut", "lanjutkan"}
_RESTART = {"mulai ulang", "/ulang", "ulang dari awal"}
_HELP = {"bantuan", "/bantuan", "minta bantuan", "minta bantuan admin", "tolong", "help", "/help"}
_SKIP = {"lewati", "lewat", "skip", "/lewati"}
_DONE = {"selesai", "sudah", "cukup", "done", "/selesai"}

# A join code, optionally after "gabung"/"kode" or Telegram's "/start" (join-codes.md).
_CODE = re.compile(
    r"^(?:/start\s+|gabung\s+|kode\s+)?([a-hj-km-np-tv-z2-9]{4})[\s-]?([a-hj-km-np-tv-z2-9]{4})$"
)
_MEDIA_TYPES = ("photo", "video", "voice", "document", "signature")
_DRAFT = ("asking", "confirming_summary")
# `step` while waiting for the one sentence of a voice-mode report (Voice Lab, roadmap 12.3).
VOICE_STEP = "__voice__"
_ACCEPTS = {
    "photo": ("photo",),
    "video": ("video",),
    "voice": ("voice",),
    "document": ("photo", "document"),
    "signature": ("photo", "document"),
}


def extract_join_code(text: str | None) -> str | None:
    """ "gabung k7m2-9qxa" → "K7M29QXA"; None when the text is not a code."""
    m = _CODE.match(normalize(text or ""))
    return (m.group(1) + m.group(2)).upper() if m else None


# --- Entry points -------------------------------------------------------------------------------


def handle(state: ConversationState, message: Inbound, ctx: EngineContext) -> Step:
    s = replace(state, answers=dict(state.answers), required_by_rules=list(state.required_by_rules),
                review_reasons=list(state.review_reasons),
                held_media=list(state.held_media))  # fmt: skip
    if s.status == "taken_over":
        return Step(s)  # the admin is answering; keep quiet
    text = normalize(message.text or "")

    code = extract_join_code(message.text)
    # Mid-report, eight bare letters may be an answer (a name); a code there needs its usual
    # form ("K7M2-9QXA") or a prefix. The service decides what claiming means (roadmap 3.6:
    # join, switch topic or add one) and keeps this state when the code is unknown.
    looks_like_code = bool(re.search(r"[\s-]", text)) or text.startswith(
        ("/start", "gabung", "kode")
    )
    if code and (s.status != "asking" or looks_like_code):
        return Step(s, effects=(ClaimCode(code),))
    if s.status == "needs_help":
        return Step(s)  # waiting for an admin
    if not ctx.topics:
        return Step(s, replies=(Outbound(copy.JOIN_FIRST),))
    if text in _HELP or message.button == "help":
        return _needs_help(s, "asked_for_help")

    unheard = message.media is not None and message.media.kind == "voice" and not message.text
    if ctx.voice_mode and unheard and s.status not in ("choosing_form", *_DRAFT):
        # A voice note the speech provider could not read: say so rather than start over.
        return Step(s, replies=(Outbound(copy.VOICE_UNREAD),))
    if (
        ctx.voice_mode
        and ctx.definition is not None
        and s.status not in ("choosing_form", *_DRAFT)
        and _is_sentence(message)
    ):
        # Voice Lab: the first message already carries the results (roadmap 12.3).
        begun = start(s, ctx)
        voiced = _voice(begun.state, message, ctx, ctx.definition, opening=False)
        if voiced is not None:
            return voiced

    if message.media is not None:
        album = _album(s, message, ctx)
        if album is not None:
            return album
        if s.status not in ("choosing_form", *_DRAFT) and message.media.kind == "photo":
            # A photo before "mulai" starts a report and answers its first photo field.
            s.held_media = [message.media.ref]
            s.media_group = message.media.group
            return _begin(s, ctx)

    if s.status == "choosing_form":
        return _choose_topic(s, message, ctx)
    if s.status == "asking" and ctx.definition is not None:
        if text in _RESTART or message.button == "restart":
            return start(s, ctx)
        return _asking(s, message, ctx, ctx.definition)
    if s.status == "confirming_summary" and ctx.definition is not None:
        return _summary_step(s, message, ctx, ctx.definition)
    # idle, identifying, submitted, joining: begin a (new) report.
    return _begin(s, ctx)


def start(state: ConversationState, ctx: EngineContext) -> Step:
    """Begin a fresh report on the active topic (after joining or picking a topic)."""
    s = ConversationState(status="asking", topic_id=state.topic_id)
    definition = ctx.definition
    if definition is None:
        s.held_media, s.media_group = list(state.held_media), state.media_group
        return Step(s)
    notes = _use_held_media(s, state, definition)
    if ctx.voice_mode and not s.answers:
        s.step = VOICE_STEP
        prompt = copy.voice_prompt(_voice_example(definition))
        greeting = copy.greet(ctx.salutation, ctx.topic_label, prompt)
        return Step(s, replies=(*notes, Outbound(greeting)))
    first = _next_field(s, definition)
    if first is None:
        summary = _show_summary(s, definition, ctx)
        return Step(summary.state, replies=(*notes, *summary.replies))
    s.step = first.key
    question = _question(s, definition, first)
    greeting = replace(question, text=copy.greet(ctx.salutation, ctx.topic_label, question.text))
    return Step(s, replies=(*notes, greeting))


def _use_held_media(
    s: ConversationState, state: ConversationState, definition: FormDefinition
) -> tuple[Outbound, ...]:
    """Photos sent before the report started answer its first photo field (up to its `max`)."""
    if not state.held_media:
        return ()
    s.media_group = state.media_group
    target = _first_photo_field(definition)
    if target is None:
        return (Outbound(copy.NO_PHOTO_FIELD),)
    high = int(target.max) if target.max else None
    files = state.held_media[:high] if high else list(state.held_media)
    s.answers[target.key] = files
    _evaluate_rules(s, definition)
    notes = [Outbound(copy.photo_first_saved(len(files)))]
    if high is not None and len(state.held_media) > high:
        notes.append(Outbound(copy.media_extra_ignored(high)))
    return tuple(notes)


def _album(s: ConversationState, message: Inbound, ctx: EngineContext) -> Step | None:
    """The rest of an album whose first photo started the report; None when the message is not
    part of it (or the open question collects photos anyway)."""
    media = message.media
    if media is None or media.group is None or media.group != s.media_group:
        return None
    if media.kind != "photo":
        return Step(s)
    if s.status not in _DRAFT:
        s.held_media.append(media.ref)  # still choosing the topic
        return Step(s)
    definition = ctx.definition
    if s.status != "asking" or definition is None:
        return Step(s)
    current = definition.field(s.step or "")
    if current is not None and current.type in _MEDIA_TYPES:
        return None
    target = _first_photo_field(definition)
    if target is None:
        return Step(s)
    files = list(s.answers.get(target.key) or [])
    high = int(target.max) if target.max else None
    if high is not None and len(files) >= high:
        return Step(s, replies=(Outbound(copy.media_extra_ignored(high)),))
    s.answers[target.key] = [*files, media.ref]
    return Step(s)


def _is_sentence(message: Inbound) -> bool:
    """A voice note's transcript, or typed text that is not a command word."""
    text = normalize(message.text or "")
    return bool(text) and (message.spoken or text not in (_START | _RESUME | _HELP))


def _voice_example(definition: FormDefinition) -> str:
    """An example sentence from the first spoken fields: "Nomor sampel …, pH …, Suhu … °C"."""
    parts = []
    for f in definition.fields:
        if f.type in SPOKEN_TYPES and len(parts) < 3:
            parts.append(f"{f.label} …" + (f" {f.unit}" if f.unit else ""))
    return ", ".join(parts)


def _voice(
    s: ConversationState,
    message: Inbound,
    ctx: EngineContext,
    definition: FormDefinition,
    *,
    opening: bool,
) -> Step | None:
    """Read many fields from one sentence (roadmap 12.1/12.3). Confident values are kept;
    doubtful and missing ones are asked next, one at a time. None when nothing was recognised
    and the message was not an answer to the voice prompt (`opening`)."""
    said = message.text or ""
    if not said.strip():
        if message.media is not None and message.media.kind == "voice":
            return Step(s, replies=(Outbound(copy.VOICE_UNREAD),))
        return Step(s, replies=(Outbound(copy.voice_nothing(_voice_example(definition))),))
    result = extract(said, definition, today=ctx.today)
    if not result.values or all(v.value is None for v in result.values):
        if not opening:
            return None
        s.failed_attempts += 1
        return Step(s, replies=(Outbound(copy.voice_nothing(_voice_example(definition))),))
    sure: list[tuple[str, str]] = []
    unsure: list[tuple[str, str]] = []
    for v in result.values:
        f = definition.field(v.field_key)
        assert f is not None
        if v.confidence >= CONFIDENT and v.value is not None:
            s.answers[f.key] = v.value
            sure.append((f.label, v.display))
        else:
            unsure.append((f.label, v.heard))
    s.voice = {
        "transcript": said,
        "audio": message.audio,
        "heard": {v.field_key: v.heard for v in result.values},
        "confidence": {v.field_key: round(v.confidence, 2) for v in result.values},
    }
    s.step = None
    s.failed_attempts = 0
    _evaluate_rules(s, definition)
    following = _advance(s, ctx, definition)
    return Step(
        following.state, replies=(Outbound(copy.voice_heard(sure, unsure)), *following.replies)
    )


def _first_photo_field(definition: FormDefinition) -> FieldDefinition | None:
    return next((f for f in definition.fields if f.type == "photo"), None)


def report_saved(code: str, ctx: EngineContext) -> Outbound:
    """Sent by the service once the SubmitReport effect created the report."""
    return Outbound(copy.report_saved(code, ctx.salutation))


# --- Topics -------------------------------------------------------------------------------------


def _begin(s: ConversationState, ctx: EngineContext) -> Step:
    if s.topic_id is None and len(ctx.topics) == 1:
        s.topic_id = ctx.topics[0].id
    if s.topic_id is None or len(ctx.topics) > 1 and s.status == "submitted":
        s.status = "choosing_form"
        s.topic_id = None
        buttons = tuple(Button(t.label, f"topic:{t.id}") for t in ctx.topics)
        return Step(s, replies=(Outbound(copy.CHOOSE_TOPIC, buttons),))
    if ctx.definition is None:
        s.status = "identifying"
        return Step(s, effects=(SelectTopic(s.topic_id),))
    return start(s, ctx)


def _choose_topic(s: ConversationState, message: Inbound, ctx: EngineContext) -> Step:
    topic_id = None
    if message.button and message.button.startswith("topic:"):
        topic_id = message.button.removeprefix("topic:")
    elif message.text:
        match = parse_choice(message.text, [Choice(t.id, t.label) for t in ctx.topics])
        topic_id = match.value if match and not match.needs_confirmation else None
    if topic_id is None or all(t.id != topic_id for t in ctx.topics):
        buttons = tuple(Button(t.label, f"topic:{t.id}") for t in ctx.topics)
        return Step(s, replies=(Outbound(copy.TOPIC_UNKNOWN, buttons),))
    s.status = "identifying"
    s.topic_id = topic_id
    return Step(s, effects=(SelectTopic(topic_id),))


# --- Asking -------------------------------------------------------------------------------------


def _asking(
    s: ConversationState, message: Inbound, ctx: EngineContext, definition: FormDefinition
) -> Step:
    if s.step == VOICE_STEP:
        voiced = _voice(s, message, ctx, definition, opening=True)
        assert voiced is not None
        return voiced
    current = definition.field(s.step or "")
    if current is None:
        return _advance(s, ctx, definition)
    text = normalize(message.text or "")

    if s.pending is not None:
        return _resolve_pending(s, message, ctx, definition, current)
    if text in _RESUME or text in _START:
        return Step(s, replies=(_question(s, definition, current),))
    if text in _SKIP or message.button == "skip":
        if _is_required(s, current):
            return Step(s, replies=(Outbound(copy.REQUIRED), _question(s, definition, current)))
        s.answers[current.key] = None
        return _committed(s, ctx, definition)

    if current.type in _MEDIA_TYPES:
        return _media(s, message, ctx, definition, current)
    if message.media is not None and message.media.kind != "voice":
        # A photo while a text question is open: carry on or start over (resume/restart are
        # handled by the service's command layer).
        buttons = (Button(copy.RESUME, "resume"), Button(copy.RESTART, "restart:yes"))
        return Step(s, replies=(Outbound(copy.DRAFT_EXISTS, buttons),))
    outcome = _read(current, message, ctx)
    if isinstance(outcome, str):
        return _failed(s, definition, current, outcome)
    value, display, needs_confirm = outcome
    if needs_confirm:
        s.pending = {"field": current.key, "value": value, "display": display}
        return Step(s, replies=(_confirm_question(current, display),))
    s.answers[current.key] = value
    return _committed(s, ctx, definition)


def _resolve_pending(
    s: ConversationState,
    message: Inbound,
    ctx: EngineContext,
    definition: FormDefinition,
    current: FieldDefinition,
) -> Step:
    pending = s.pending or {}
    answer = {"yes": True, "no": False}.get(message.button or "")
    if answer is None:
        answer = parse_yes_no(message.text or "")
    if answer is None:
        # A new answer instead of yes/no: read it as the answer to the question.
        if message.text and normalize(message.text) not in ("",):
            s.pending = None
            return _asking(s, message, ctx, definition)
        return Step(
            s,
            replies=(Outbound(copy.CONFIRM_FIRST), _confirm_question(current, pending["display"])),
        )
    s.pending = None
    if not answer:
        return Step(s, replies=(_question(s, definition, current),))
    s.answers[current.key] = pending["value"]
    return _committed(s, ctx, definition)


def _media(
    s: ConversationState,
    message: Inbound,
    ctx: EngineContext,
    definition: FormDefinition,
    current: FieldDefinition,
) -> Step:
    files: list[str] = list(s.answers.get(current.key) or [])
    low = int(current.min or (1 if _is_required(s, current) else 0))
    high = int(current.max) if current.max else None
    text = normalize(message.text or "")
    if message.media and message.media.kind in _ACCEPTS[current.type]:
        files.append(message.media.ref)
        s.answers[current.key] = files
        s.failed_attempts = 0
        if high is not None and len(files) >= high:
            return _committed(s, ctx, definition)
        more = high is None or len(files) < high
        reply = copy.media_received(current.type, len(files), more)
        if len(files) >= max(low, 1):
            return Step(s, replies=(Outbound(reply, (Button(copy.DONE, "done"),)),))
        return Step(s, replies=(Outbound(reply),))
    if text in _DONE or message.button == "done":
        if len(files) >= max(low, 1):
            return _committed(s, ctx, definition)
        return _failed(s, definition, current, copy.media_too_few(current.type, max(low, 1)))
    if message.media and message.media.kind == "voice":
        return _failed(s, definition, current, copy.NEED_MEDIA[current.type])
    return _failed(s, definition, current, copy.NEED_MEDIA[current.type])


def _read(f: FieldDefinition, message: Inbound, ctx: EngineContext) -> tuple[Any, str, bool] | str:
    """(value, how it is shown, needs confirmation) or the reason it was not accepted."""
    if message.media and message.media.kind == "voice" and f.type != "voice":
        return copy.VOICE_LATER
    raw = message.text or ""
    if f.type in ("short_text", "long_text"):
        cleaned = raw.strip()
        return (cleaned, cleaned, False) if cleaned else copy.EMPTY_TEXT

    if f.type == "number":
        parsed = parse_number(raw, units=ctx.units)
        if parsed is None:
            return copy.NOT_A_NUMBER
        field_unit = _unit_code(f.unit)
        if parsed.unit and field_unit and parsed.unit != field_unit:
            return copy.wrong_unit(f.unit or "")
        value = parsed.value
        if (f.min is not None and value < Decimal(str(f.min))) or (
            f.max is not None and value > Decimal(str(f.max))
        ):
            return copy.out_of_range(f.min, f.max, f.unit)
        display = copy.number(value) + (f" {f.unit}" if f.unit else "")
        # Written in words ("satu setengah"): say what was understood before saving it.
        return (str(value), display, not any(c.isdigit() for c in raw))

    if f.type == "single_choice":
        options = [Choice(o.value, o.label) for o in f.options]
        button = (message.button or "").removeprefix("opt:")
        if message.button and any(o.value == button for o in options):
            label = next(o.label for o in options if o.value == button)
            return (button, label, False)
        match = parse_choice(raw, options)
        if match is None:
            return copy.NOT_A_CHOICE
        return (match.value, match.label, match.needs_confirmation)

    if f.type == "multi_choice":
        options = [Choice(o.value, o.label) for o in f.options]
        result = parse_multi_choice(raw, options)
        if result.unknown or not result.matches:
            return copy.unknown_choices(result.unknown) if result.unknown else copy.NOT_A_CHOICE
        count = len(result.matches)
        if (f.min and count < f.min) or (f.max and count > f.max):
            return copy.choice_count(f.min, f.max)
        labels = ", ".join(m.label for m in result.matches)
        guessed = any(m.needs_confirmation for m in result.matches)
        return ([m.value for m in result.matches], labels, guessed)

    if f.type == "datetime":
        day = parse_date(raw, today=ctx.today)
        return (day.isoformat(), copy.date(day), False) if day else copy.NOT_A_DATE

    if f.type == "location":
        if message.location:
            loc = message.location
            if f.max_accuracy_m and loc.accuracy_m and loc.accuracy_m > f.max_accuracy_m:
                return copy.location_inaccurate(f.max_accuracy_m)
            value = {"lat": loc.lat, "lng": loc.lng, "accuracy_m": loc.accuracy_m}
            return (value, "lokasi terlampir", False)
        typed_allowed = not f.answer_modes or "name" in f.answer_modes
        if raw.strip() and typed_allowed:
            return ({"name": raw.strip()}, raw.strip(), False)
        return copy.NEED_LOCATION

    return copy.EMPTY_TEXT


def _failed(
    s: ConversationState, definition: FormDefinition, current: FieldDefinition, reason: str
) -> Step:
    s.failed_attempts += 1
    if s.failed_attempts >= MAX_FAILURES:
        buttons = [Button(copy.HELP, "help")]
        if not _is_required(s, current):
            buttons.insert(0, Button(copy.SKIP, "skip"))
        return Step(s, replies=(Outbound(reason), Outbound(copy.THREE_FAILS, tuple(buttons))))
    return Step(s, replies=(Outbound(reason), _question(s, definition, current)))


def _committed(s: ConversationState, ctx: EngineContext, definition: FormDefinition) -> Step:
    s.failed_attempts = 0
    _evaluate_rules(s, definition)
    if s.editing:
        s.editing = False
        return _show_summary(s, definition, ctx)
    return _advance(s, ctx, definition)


def _advance(s: ConversationState, ctx: EngineContext, definition: FormDefinition) -> Step:
    following = _next_field(s, definition)
    if following is None:
        return _show_summary(s, definition, ctx)
    s.step = following.key
    return Step(s, replies=(_question(s, definition, following),))


def _next_field(s: ConversationState, definition: FormDefinition) -> FieldDefinition | None:
    return next((f for f in definition.fields if f.key not in s.answers), None)


def _is_required(s: ConversationState, f: FieldDefinition) -> bool:
    return f.required or f.key in s.required_by_rules


def _evaluate_rules(s: ConversationState, definition: FormDefinition) -> None:
    """Recompute rule effects from all answers, so changing an answer also undoes them."""
    required: list[str] = []
    reasons: list[str] = []
    for i, rule in enumerate(definition.rules):
        answer = s.answers.get(rule.if_.field)
        if not _equals(answer, rule.if_.equals):
            continue
        if rule.then.require:
            required.append(rule.then.require)
            # A field skipped while optional must be asked again now that it is required.
            if s.answers.get(rule.then.require, "missing") is None:
                del s.answers[rule.then.require]
        if rule.then.needs_review:
            reasons.append(f"rule:{i}")
    for f in definition.fields:
        value = s.answers.get(f.key)
        if f.type == "number" and f.review_above is not None and value is not None:
            if Decimal(str(value)) > Decimal(str(f.review_above)):
                reasons.append(f"review_above:{f.key}")
    s.required_by_rules = required
    s.review_reasons = reasons


def _equals(answer: Any, expected: Any) -> bool:
    if answer is None:
        return False
    if isinstance(answer, list):
        return expected in answer
    if isinstance(expected, bool):
        return answer == expected
    if isinstance(expected, int | float) and not isinstance(expected, bool):
        try:
            return Decimal(str(answer)) == Decimal(str(expected))
        except ArithmeticError:
            return False
    return str(answer) == str(expected)


# --- Questions and summary ----------------------------------------------------------------------


def _question(s: ConversationState, definition: FormDefinition, f: FieldDefinition) -> Outbound:
    asked = [x for x in definition.fields if x.key in s.answers or x.key == f.key]
    position = len(asked)
    total = len(definition.fields)
    text = f"{position}/{total} {f.question}"
    buttons: list[Button] = []
    if f.type == "single_choice" and len(f.options) <= MAX_BUTTONS:
        buttons = [Button(o.label, f"opt:{o.value}") for o in f.options]
    elif f.type in ("single_choice", "multi_choice"):
        listed = "\n".join(f"{i}. {o.label}" for i, o in enumerate(f.options, 1))
        text = f"{text}\n{listed}"
    if not _is_required(s, f):
        text = f"{text} {copy.OPTIONAL_HINT}"
        buttons.append(Button(copy.SKIP, "skip"))
    return Outbound(text, tuple(buttons), ask_location=f.type == "location")


def _confirm_question(f: FieldDefinition, display: str) -> Outbound:
    if f.type in ("single_choice", "multi_choice"):
        return Outbound(
            copy.did_you_mean(display),
            (Button(f"{copy.YES}, {display}", "yes"), Button(copy.NOT_THIS, "no")),
        )
    return Outbound(
        copy.confirm_value(display), (Button(copy.YES, "yes"), Button(copy.CHANGE, "no"))
    )


def _show_summary(s: ConversationState, definition: FormDefinition, ctx: EngineContext) -> Step:
    s.status = "confirming_summary"
    s.step = None
    lines = [(f.label, _display(f, s.answers.get(f.key))) for f in definition.fields]
    buttons = (Button(copy.SUBMIT, "submit"), Button(copy.EDIT, "edit"))
    return Step(s, replies=(Outbound(copy.summary(lines), buttons),))


def _summary_step(
    s: ConversationState, message: Inbound, ctx: EngineContext, definition: FormDefinition
) -> Step:
    button = message.button or ""
    text = normalize(message.text or "")
    if button == "submit" or text in ("kirim", "kirim sekarang") or parse_yes_no(text) is True:
        s.status = "submitted"
        effect = SubmitReport(
            dict(s.answers), bool(s.review_reasons), tuple(s.review_reasons), voice=s.voice
        )
        return Step(s, effects=(effect,))
    if button == "edit" or text in ("ubah", "ubah jawaban") or parse_yes_no(text) is False:
        buttons = tuple(Button(f.label, f"edit:{f.key}") for f in definition.fields)
        return Step(s, replies=(Outbound(copy.EDIT_WHICH, buttons),))
    if button.startswith("edit:") and definition.field(button.removeprefix("edit:")):
        key = button.removeprefix("edit:")
        s.status = "asking"
        s.editing = True
        s.step = key
        s.answers.pop(key, None)
        f = definition.field(key)
        assert f is not None
        return Step(s, replies=(_question(s, definition, f),))
    if text in _RESTART:
        return start(s, ctx)
    return Step(
        s,
        replies=(
            Outbound(copy.SUBMIT_FIRST, (Button(copy.SUBMIT, "submit"), Button(copy.EDIT, "edit"))),
        ),
    )


def _display(f: FieldDefinition, value: Any) -> str:
    if value is None:
        return "-"
    if f.type == "number":
        return copy.number(Decimal(str(value))) + (f" {f.unit}" if f.unit else "")
    if f.type == "single_choice":
        return next((o.label for o in f.options if o.value == value), str(value))
    if f.type == "multi_choice":
        labels = {o.value: o.label for o in f.options}
        return ", ".join(str(labels.get(v, v)) for v in value)
    if f.type == "datetime":
        return copy.date(dt.date.fromisoformat(value))
    if f.type == "location":
        return value.get("name") or "lokasi terlampir"
    if f.type in _MEDIA_TYPES:
        return f"{len(value)} {copy.MEDIA_WORD.get(f.type, 'berkas')}"
    return str(value)


def _needs_help(s: ConversationState, reason: Any) -> Step:
    s.status = "needs_help"
    return Step(s, replies=(Outbound(copy.HELP_SENT),), effects=(NeedsHelp(reason, s.step),))


def _unit_code(unit: str | None) -> str | None:
    if not unit:
        return None
    return DEFAULT_UNITS.get(unit.strip().lower(), unit.strip().lower())
