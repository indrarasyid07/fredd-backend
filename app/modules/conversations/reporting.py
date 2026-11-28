"""The report flow on a real chat (roadmap 3.7): load the conversation of the chat's active
topic, run the pure engine (`engine/machine.py`), save its state, and carry out its effects
(another topic, the report itself, a call for help).

The official commands from roadmap 3.0 that touch more than one conversation or need a
confirmation live here, before the engine: `berhenti`, `batal`, `topik`, `mulai ulang`,
`bantuan`, and `mulai` while a draft is open (conversation-engine.md "Kata perintah resmi").

Everything runs inside `process_chat`'s transaction: the report, `status = submitted` and the
reply rows commit together.
"""

import datetime as dt
import logging
from dataclasses import dataclass, field, replace
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_storage
from app.core.time import now_utc
from app.modules.activity import service as activity
from app.modules.agent import pause as agent_pause
from app.modules.agent import rules as agent_rules
from app.modules.agent import service as agent_settings
from app.modules.agent.rules_schemas import EscalationRule
from app.modules.agent.schemas import AgentSettings
from app.modules.ai import answers, vision
from app.modules.audit import service as audit
from app.modules.channels.models import Channel
from app.modules.conversations import escalation, joining, reminders, repository
from app.modules.conversations.engine import copy, machine
from app.modules.conversations.engine.parsers import normalize
from app.modules.conversations.engine.types import (
    Button,
    ClaimCode,
    ConversationState,
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
from app.modules.conversations.models import Conversation, Message
from app.modules.extension_workers import service as workers
from app.modules.extension_workers.models import ExtensionWorker, FormAssignment
from app.modules.forms import service as forms
from app.modules.forms.errors import FormVersionNotFound
from app.modules.forms.schemas import FormDefinition
from app.modules.reports import service as reports

logger = logging.getLogger(__name__)

# Buttons of the confirmations handled here (the engine never sees them).
STOP_YES, STOP_NO = "stop:yes", "stop:no"
CANCEL_YES, CANCEL_NO = "cancel:yes", "cancel:no"
RESTART_YES, RESTART_NO = "restart:yes", "restart:no"
RESUME = "resume"
TOPIC_PREFIX = "topic:"
# Session `info` key: (workspace id, report id) of reports created in this transaction.
NEW_REPORTS = "conversations.new_reports"

_STOP = {"berhenti", "/berhenti", "stop", "/stop", "keluar"}
_CANCEL = {"batal", "/batal", "batalkan"}
_TOPIC = {"topik", "/topik", "ganti topik"}
_RESTART = {"mulai ulang", "/ulang", "ulang dari awal"}
_HELP_LIST = {"bantuan", "/bantuan", "help", "/help"}
_START = {"mulai", "/mulai", "/start", "start", "lapor", "laporan baru"}
_DRAFT = ("asking", "confirming_summary")


@dataclass
class _Run:
    """One message's work on one chat: the active topic's worker and conversation."""

    db: AsyncSession
    chat: joining.Chat
    worker: ExtensionWorker
    assignment: FormAssignment
    conversation: Conversation
    topics: list[repository.TopicRow]
    message: Message
    definition: FormDefinition | None = None
    # The structure is in voice mode (Voice Lab): one message fills many fields.
    voice_mode: bool = False
    # The organization's Pengaturan agent (loaded with the context).
    agent: AgentSettings = field(default_factory=AgentSettings)


async def handle(db: AsyncSession, chat: joining.Chat, message: Message) -> list[Outbound]:
    """Replies for a message from a chat that has an active topic (joining handled the rest)."""
    back_to = db.info.pop(joining.BACK_TO_TOPIC, None)
    run = await _load(db, chat, message)
    if run is None:
        return []
    paused = await agent_pause.paused_since(db, run.conversation.workspace_id)
    if paused is not None:
        return _paused_reply(run, paused)
    replies = await _handle(run, message, back_to)
    # The worker wrote: an open draft gets a fresh reminder, anything else none (roadmap 7.1).
    await reminders.schedule(db, run.conversation, message.channel_sent_at or now_utc())
    return replies


def _paused_reply(run: _Run, paused_at: str) -> list[Outbound]:
    """Jeda agent (6.6): the message is kept; one notice per worker per pause, then quiet. An
    admin answering a taken-over chat is not interrupted."""
    conversation = run.conversation
    if conversation.status == "taken_over" or conversation.state.get("pause_notified") == paused_at:
        return []
    conversation.state = {**conversation.state, "pause_notified": paused_at}
    return [Outbound(copy.AGENT_PAUSED)]


async def _handle(run: _Run, message: Message, back_to: str | None) -> list[Outbound]:
    if back_to is not None:
        # The code or QR of a topic this chat already has: go back to it, draft and all.
        return await _switch(run, back_to, note=True)
    if run.conversation.status == "taken_over":
        return []  # an admin is answering
    if run.worker.confirmed_at is None:
        # Reports need a confirmed binding (join-codes.md): ask again.
        return [
            Outbound(
                copy.CONFIRM_TOPIC_FIRST,
                buttons=(Button(copy.KEEP, joining.KEEP), Button(copy.NOT_MINE, joining.CHANGE)),
            )
        ]
    refused = message.payload.get("media_refused")
    if refused is not None:
        return [Outbound(copy.MEDIA_TOO_LARGE if refused == "too_large" else copy.MEDIA_WRONG_TYPE)]
    inbound = to_inbound(message)
    if inbound is None:
        return [Outbound(copy.UNSUPPORTED)]
    command = await _command(run, inbound)
    if command is not None:
        return command
    matched = await _keyword_rule(run, inbound)
    if matched is not None and matched.action == "handover":
        return [Outbound(copy.HELP_SENT)]
    return await _engine(run, inbound)


async def _keyword_rule(run: _Run, inbound: Inbound) -> EscalationRule | None:
    """Aturan ambil alih with a keyword (roadmap 6.7): hand the chat to an admin, or only alert
    them. Not while an admin is already asked or answering."""
    if run.conversation.status in ("needs_help", "taken_over"):
        return None
    rule = agent_rules.keyword_rule(
        await agent_rules.get_rules(run.db, run.conversation.workspace_id), inbound.text
    )
    if rule is None:
        return None
    if rule.action == "handover":
        step = run.conversation.step
        field = None
        if step and await _definition_for(run) and run.definition is not None:
            found = run.definition.field(step)
            field = found.label if found else None
        await escalation.hand_over(run.db, run.conversation, rule, field=step, field_label=field)
    else:
        await escalation.alert(run.db, run.conversation, rule, trigger="keyword")
    return rule


async def _definition_for(run: _Run) -> bool:
    """Load the structure the open draft follows, for the field's label."""
    if run.definition is None and run.conversation.form_version_id is not None:
        try:
            version = await forms.get_version_definition(
                run.db, run.conversation.workspace_id, run.conversation.form_version_id
            )
        except FormVersionNotFound:
            return False
        run.definition = version.definition
    return run.definition is not None


async def _load(db: AsyncSession, chat: joining.Chat, message: Message) -> _Run | None:
    assignment = await workers.active_assignment(db, chat.channel_id, chat.chat_id)
    if assignment is None:
        return None
    worker = await workers.get_by_id(db, assignment.extension_worker_id)
    if worker is None or worker.status != "active":
        return None
    conversation = await repository.get_conversation(db, worker.id, assignment.form_id)
    if conversation is None:
        conversation = Conversation(
            workspace_id=assignment.workspace_id,
            extension_worker_id=worker.id,
            form_id=assignment.form_id,
            channel_id=chat.channel_id,
            chat_id=chat.chat_id,
            state=ConversationState(topic_id=str(assignment.form_id)).to_json(),
        )
        db.add(conversation)
        await db.flush()
    identity = worker.telegram_user_id or chat.chat_id
    topics = await repository.list_chat_topics(db, identity)
    return _Run(db, chat, worker, assignment, conversation, topics, message)


def to_inbound(message: Message) -> Inbound | None:
    """A stored message as the engine reads it; None for kinds it cannot use."""
    p = message.payload
    if message.kind == "text":
        return Inbound(text=message.body or "")
    if message.kind == "button":
        return Inbound(button=message.body or "")
    if message.kind == "location":
        try:
            lat, lng = float(p["lat"]), float(p["lng"])
        except KeyError, TypeError, ValueError:
            return None
        accuracy = p.get("accuracy_m")
        return Inbound(location=Location(lat, lng, float(accuracy) if accuracy else None))
    if message.kind == "voice" and p.get("transcript") is not None:
        if p.get("transcribed_as") == "answer" and message.media_key:
            # A spoken answer (roadmap 12.7): the words answer a typed question, the file
            # answers a voice question; the engine confirms what it heard before saving.
            return Inbound(
                text=str(p["transcript"]),
                spoken=True,
                audio=message.media_key,
                media=Media("voice", message.media_key),
            )
        # A voice note of a voice-mode topic, transcribed (Voice Lab, roadmap 12.3).
        return Inbound(text=str(p["transcript"]), spoken=True, audio=message.media_key)
    if message.kind in ("photo", "video", "voice", "document") and p.get("file_id"):
        # The stored copy (roadmap 3.8); the Telegram file reference when it could not be made.
        ref = message.media_key or f"telegram:{p['file_id']}"
        group = p.get("media_group_id")
        return Inbound(media=Media(message.kind, ref, str(group) if group else None))  # type: ignore[arg-type]
    return None


# --- Commands ----------------------------------------------------------------------------------


async def _command(run: _Run, inbound: Inbound) -> list[Outbound] | None:
    text = normalize(inbound.text or "")
    button = inbound.button or ""
    state = ConversationState.from_json(run.conversation.state)
    has_draft = state.status in _DRAFT and bool(state.answers)

    if text in _STOP:
        return [_confirm(copy.STOP_CONFIRM, copy.YES_STOP, STOP_YES, STOP_NO)]
    if button == STOP_YES:
        await _stop(run)
        return [Outbound(copy.STOPPED)]
    if button == STOP_NO:
        return [Outbound(copy.STOP_CANCELLED)]
    if button in (CANCEL_NO, RESTART_NO):
        # Carry on where they were: repeat the open question, if any.
        if state.status in _DRAFT:
            return [Outbound(copy.KEEP_GOING), *await _engine(run, Inbound(text="lanjut"))]
        return [Outbound(copy.KEEP_GOING)]

    if text in _CANCEL:
        if state.status not in _DRAFT:
            return [Outbound(copy.NO_DRAFT)]
        return [_confirm(copy.CANCEL_CONFIRM, copy.YES_CANCEL, CANCEL_YES, CANCEL_NO)]
    if button == CANCEL_YES:
        _save(run.conversation, ConversationState(topic_id=state.topic_id))
        return [Outbound(copy.DRAFT_CANCELLED)]

    if text in _RESTART and has_draft:
        return [_confirm(copy.RESTART_CONFIRM, copy.YES_RESTART, RESTART_YES, RESTART_NO)]
    if button == RESTART_YES or (text in _RESTART and not has_draft):
        fresh = ConversationState(topic_id=str(run.assignment.form_id))
        return await _engine(run, Inbound(text="mulai"), state=fresh)
    if text in _START and has_draft:
        buttons = (Button(copy.RESUME, RESUME), Button(copy.RESTART, RESTART_YES))
        return [Outbound(copy.DRAFT_EXISTS, buttons)]
    if button == RESUME:
        return await _engine(run, Inbound(text="lanjut"))

    if text in _HELP_LIST:
        return [Outbound(copy.HELP_TEXT, (Button(copy.HELP, "help"),))]
    if text in _TOPIC:
        if len(run.topics) < 2:
            current = _label(run, run.assignment)
            return [Outbound(copy.only_topic(*current))]
        return [Outbound(copy.CHOOSE_TOPIC, _topic_buttons(run))]
    if button.startswith(TOPIC_PREFIX):
        return await _switch(run, button.removeprefix(TOPIC_PREFIX))
    return None


def _confirm(text: str, yes: str, yes_value: str, no_value: str) -> Outbound:
    return Outbound(text, (Button(yes, yes_value), Button(copy.CANCEL, no_value)))


def _label(run: _Run, assignment: FormAssignment) -> tuple[str, str]:
    for a, organization, form in run.topics:
        if a.id == assignment.id:
            return organization, form
    return "", ""


def _topic_buttons(run: _Run) -> tuple[Button, ...]:
    return tuple(
        Button(copy.topic_title(org, form), f"{TOPIC_PREFIX}{a.form_id}")
        for a, org, form in run.topics
    )


async def _stop(run: _Run) -> None:
    """Opt-out (B-XXX "berhenti"): every topic of this chat ends, drafts and reminders go."""
    now = now_utc()
    for assignment, _, _ in run.topics:
        conversation = await repository.get_conversation(
            run.db, assignment.extension_worker_id, assignment.form_id
        )
        if conversation is not None:
            _save(conversation, ConversationState(topic_id=str(assignment.form_id)))
            conversation.next_reminder_at = None
        await workers.leave(run.db, assignment, now)
        await audit.record(
            run.db,
            workspace_id=assignment.workspace_id,
            actor_user_id=None,
            action="extension_worker.opted_out",
            target=str(assignment.extension_worker_id),
            details={"form_id": str(assignment.form_id)},
        )
    await workers.set_active(run.db, run.chat.channel_id, run.chat.chat_id, None)


async def _switch(run: _Run, form_id: str, *, note: bool = False) -> list[Outbound]:
    """Move the chat to another of its topics; that topic's draft (if any) carries on. `note`
    first says where the chat went (when a join code, not a topic button, asked for it)."""
    found = next(((a, o, f) for a, o, f in run.topics if str(a.form_id) == form_id), None)
    if found is None:
        return [Outbound(copy.TOPIC_UNKNOWN, _topic_buttons(run))]
    target = found[0]
    state = ConversationState.from_json(run.conversation.state)
    if state.status == "choosing_form":
        _save(run.conversation, ConversationState(topic_id=state.topic_id))
    notes = [Outbound(copy.back_to_topic(found[1], found[2]))] if note else []
    if target.id != run.assignment.id:
        await workers.set_active(run.db, run.chat.channel_id, run.chat.chat_id, target.id)
        switched = await _load(run.db, run.chat, run.message)
        if switched is None:
            return []
        if state.held_media:
            notes += _carry_photos(state, run.assignment, switched)
        run = switched
    return [*notes, *await _engine(run, Inbound(text="mulai"))]


def _carry_photos(state: ConversationState, source: FormAssignment, target: _Run) -> list[Outbound]:
    """Photos sent before choosing a topic move to the chosen topic's new report. They were
    stored under the organization of the topic active when they arrived, so they only move within
    that organization; for another one the worker is asked to send them again."""
    if source.workspace_id != target.assignment.workspace_id:
        return [Outbound(copy.PHOTO_RESEND)]
    held = ConversationState.from_json(target.conversation.state)
    if held.status in _DRAFT:
        return []  # that topic's open draft carries on; the photos are not forced into it
    held.held_media, held.media_group = state.held_media, state.media_group
    _save(target.conversation, held)
    return []


# --- Engine ------------------------------------------------------------------------------------


async def _engine(
    run: _Run, inbound: Inbound, *, state: ConversationState | None = None
) -> list[Outbound]:
    current = state or ConversationState.from_json(run.conversation.state)
    if current.topic_id is None:
        current.topic_id = str(run.assignment.form_id)
    closed = await _prepare_definition(run, current)
    if closed is not None:
        return [closed]
    ctx = await _context(run)
    step = machine.handle(current, inbound, ctx)
    if step.unread is not None and inbound.text and run.agent.read_free_answers:
        rewrite = await _ai_reading(ctx, step.unread, inbound.text)
        if rewrite is not None:
            step = machine.handle(current, replace(inbound, ai_text=rewrite), ctx)
    elif step.unread_voice and inbound.text and run.agent.read_free_answers:
        values = await _ai_sentence(ctx, step.unread_voice, inbound.text)
        if values:
            step = machine.handle(current, replace(inbound, ai_values=values), ctx)
    elif step.read_photo and run.agent.voice_and_photos:
        photo_values = await _ai_photo(ctx, step.read_photo, step.read_keys)
        if photo_values is not None:  # {} = read, nothing found: the engine says so
            step = machine.handle(current, replace(inbound, ai_values=photo_values), ctx)
    return await _apply(run, step, ctx)


async def _ai_reading(ctx: EngineContext, field_key: str, said: str) -> str | None:
    """A language model's reading of an answer the parsers could not read (roadmap 12.7);
    None when it is off or could not read it either. The engine asks the worker to confirm."""
    reader = answers.get_answer_reader()
    f = ctx.definition.field(field_key) if ctx.definition is not None else None
    if reader is None or f is None:
        return None
    return await reader.read(f, said, today=ctx.today)


async def _ai_sentence(ctx: EngineContext, keys: tuple[str, ...], said: str) -> dict[str, str]:
    """A language model's reading of a Voice Lab sentence for the fields the rules missed
    (roadmap 12.7); empty when it is off or read nothing. The engine has each value confirmed."""
    reader = answers.get_sentence_reader()
    if reader is None or ctx.definition is None:
        return {}
    return await reader.read_sentence(ctx.definition, keys, said, today=ctx.today)


async def _ai_photo(ctx: EngineContext, ref: str, keys: tuple[str, ...]) -> dict[str, str] | None:
    """ "Baca struk dan foto": a language model reads the stored photo for the answers not given
    yet. None when it is off, the photo is not stored (only a Telegram reference) or not an
    image, or reading failed; the engine then asks as usual."""
    reader = answers.get_photo_reader()
    if reader is None or ctx.definition is None or ref.startswith("telegram:"):
        return None
    try:
        image = await get_storage().get(ref)
    except Exception:  # a missing or unreadable file: nothing to read
        logger.warning("photo %s not readable for its values", ref, exc_info=True)
        return None
    content_type = vision.image_type(image)
    if content_type is None:
        return None
    field = next(
        (f for f in ctx.definition.fields if f.read_values and f.type in ("photo", "document")),
        None,
    )
    context = f"Form: {ctx.topic_label}" + (
        f"\nPhoto question: {field.question}" if field is not None else ""
    )
    return await reader.read_photo(
        ctx.definition, keys, image, content_type, context=context, today=ctx.today
    )


async def _prepare_definition(run: _Run, state: ConversationState) -> Outbound | None:
    """The form version this conversation runs on. A draft keeps the version it started with
    even after a new one is published; a new report takes the current version."""
    conversation = run.conversation
    keep = state.status in _DRAFT and conversation.form_version_id is not None
    form = await forms.get_form(run.db, conversation.workspace_id, conversation.form_id)
    run.voice_mode = (form.settings or {}).get("input_mode") == "voice"
    if not keep:
        if form.status not in ("pilot", "active") or form.current_version_id is None:
            return Outbound(copy.topic_closed(*_label(run, run.assignment)))
        conversation.form_version_id = form.current_version_id
    assert conversation.form_version_id is not None
    try:
        version = await forms.get_version_definition(
            run.db, conversation.workspace_id, conversation.form_version_id
        )
    except FormVersionNotFound:
        return Outbound(copy.topic_closed(*_label(run, run.assignment)))
    run.definition = version.definition
    return None


async def _context(run: _Run) -> EngineContext:
    tz = ZoneInfo(await repository.get_timezone_name(run.db, run.conversation.workspace_id))
    run.agent = await agent_settings.get_settings(run.db, run.conversation.workspace_id)
    organization, form = _label(run, run.assignment)
    return EngineContext(
        salutation=run.worker.name.split()[0] if run.worker.name else "",
        today=dt.datetime.now(tz).date(),
        topics=[Topic(str(a.form_id), copy.topic_title(o, f)) for a, o, f in run.topics],
        definition=run.definition,
        topic_label=copy.topic_title(organization, form),
        voice_mode=run.voice_mode,
        agent=agent_settings.voice_of(run.agent),
    )


async def _apply(run: _Run, step: Step, ctx: EngineContext) -> list[Outbound]:
    replies = list(step.replies)
    _save(run.conversation, step.state)
    for effect in step.effects:
        if isinstance(effect, SubmitReport):
            replies.append(await _submit(run, effect, ctx))
        elif isinstance(effect, SelectTopic):
            replies.extend(await _switch(run, effect.topic_id))
        elif isinstance(effect, NeedsHelp):
            await audit.record(
                run.db,
                workspace_id=run.conversation.workspace_id,
                actor_user_id=None,
                action="conversation.needs_help",
                target=str(run.conversation.id),
                details={"reason": effect.reason, "field": effect.field},
            )
            field = run.definition.field(effect.field) if run.definition and effect.field else None
            await _event(
                run,
                "needs_help",
                "needs_help",
                reason=effect.reason,
                field=effect.field,
                field_label=field.label if field else None,
            )
        elif isinstance(effect, ClaimCode):
            # A bare code outside a question: joining decides (join, switch or add a topic).
            current = await workers.active_assignment(run.db, run.chat.channel_id, run.chat.chat_id)
            claimed = await joining.claim(run.db, run.chat, run.message, effect.code, current)
            back_to = run.db.info.pop(joining.BACK_TO_TOPIC, None)
            if claimed is None and back_to is not None:
                claimed = await _switch(run, back_to, note=True)  # a topic this chat already has
            replies.extend(claimed or [])
    return replies


async def _submit(run: _Run, effect: SubmitReport, ctx: EngineContext) -> Outbound:
    conversation = run.conversation
    assert run.definition is not None and conversation.form_version_id is not None
    report = await reports.create_report(
        run.db,
        workspace_id=conversation.workspace_id,
        form_id=conversation.form_id,
        form_version_id=conversation.form_version_id,
        definition=run.definition,
        extension_worker_id=run.worker.id,
        conversation_id=conversation.id,
        answers=effect.answers,
        needs_review=effect.needs_review,
        review_reasons=effect.review_reasons,
        voice=effect.voice,
    )
    logger.info("report %s created", report.id)
    rules = await agent_rules.get_rules(run.db, conversation.workspace_id)
    for rule in agent_rules.condition_rules(rules, report.condition):
        await escalation.alert(
            run.db, conversation, rule, trigger="condition", code=report.code,
            condition=report.condition, report_id=str(report.id),
        )  # fmt: skip
    await _event(
        run,
        "report_received",
        "needs_review" if effect.needs_review else "done",
        report_id=str(report.id),
        code=report.code,
    )
    # Jobs for the new report start once the chat's transaction commits (`process_chat`).
    run.db.info.setdefault(NEW_REPORTS, []).append((conversation.workspace_id, report.id))
    return machine.report_saved(report.code, ctx)


async def _event(run: _Run, type: str, status: str, **details: str | None) -> None:
    """One line in the organization's Aktivitas Agent log (roadmap 6.2)."""
    channel = await run.db.get(Channel, run.chat.channel_id)
    await activity.record(
        run.db,
        workspace_id=run.conversation.workspace_id,
        type=type,
        status=status,
        channel=channel.type if channel else None,
        extension_worker_id=run.worker.id,
        conversation_id=run.conversation.id,
        details={"form_name": _label(run, run.assignment)[1], **details},
    )


def _save(conversation: Conversation, state: ConversationState) -> None:
    conversation.state = state.to_json()
    conversation.status = state.status
    conversation.step = state.step
    conversation.failed_attempts = state.failed_attempts
