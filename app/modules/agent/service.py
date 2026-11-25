"""Pengaturan agent: read and save an organization's agent settings, and run a test chat.

Settings live in `workspaces.settings["agent"]`, so the shared bot reads them per message and a
change applies to the next message, without a restart. Missing keys fall back to the defaults,
which reproduce the bot's original wording.

The test chat is stateless: the dashboard sends the whole chat each time and it is replayed
through the same engine the bot uses, with the settings being tried. Nothing is stored: no
conversation, no report, no worker.
"""

import datetime as dt
import uuid
from dataclasses import replace
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.errors import AppError
from app.core.time import now_utc
from app.modules.agent.schemas import (
    AgentPreviewOut,
    AgentSettings,
    AgentSettingsOut,
    AgentTestIn,
    AgentTestOut,
    ChatButtonOut,
    ChatReplyOut,
    ChatTurnOut,
)
from app.modules.ai import answers, openai_client
from app.modules.audit import service as audit
from app.modules.conversations.engine import copy, machine
from app.modules.conversations.engine.types import (
    AgentVoice,
    ClaimCode,
    ConversationState,
    EngineContext,
    Inbound,
    NeedsHelp,
    Outbound,
    SelectTopic,
    Step,
    SubmitReport,
    Topic,
)
from app.modules.forms import service as forms
from app.modules.workspaces import repository as workspaces_repo
from app.modules.workspaces.service import ActiveMember

SETTINGS_KEY = "agent"
# Who the preview and the test chat talk to.
SAMPLE_SALUTATION = "Budi"
SAMPLE_TOPIC = "Survei Kondisi Tanaman"
TEST_REPORT_CODE = "UJI-0001"


class FormNotTestable(AppError):
    status_code = 409
    code = "form_not_testable"
    message = "Struktur data ini belum punya versi terbit. Terbitkan dulu, lalu uji."


# --- Settings -----------------------------------------------------------------------------------


async def get_settings(db: AsyncSession, workspace_id: uuid.UUID) -> AgentSettings:
    """The organization's settings, defaults for anything never saved (or saved by an older
    version and no longer valid)."""
    stored = (await workspaces_repo.get_settings(db, workspace_id)).get(SETTINGS_KEY) or {}
    known = {k: v for k, v in stored.items() if k in AgentSettings.model_fields}
    try:
        return AgentSettings.model_validate(known)
    except ValueError:
        return AgentSettings()


def voice_of(agent: AgentSettings) -> AgentVoice:
    return AgentVoice(name=agent.name, style=agent.style, greeting=agent.greeting)


async def get_settings_out(db: AsyncSession, workspace_id: uuid.UUID) -> AgentSettingsOut:
    stored = (await workspaces_repo.get_settings(db, workspace_id)).get(SETTINGS_KEY) or {}
    current = await get_settings(db, workspace_id)
    updated = stored.get("updated_at")
    return AgentSettingsOut(
        **current.model_dump(),
        updated_at=dt.datetime.fromisoformat(updated) if isinstance(updated, str) else None,
        ai_available=app_settings.llm_provider == "openai"
        and openai_client.get_client() is not None,
        voice_available=app_settings.stt_provider == "openai"
        and openai_client.get_client() is not None,
    )


async def update_settings(
    db: AsyncSession, member: ActiveMember, data: AgentSettings
) -> AgentSettingsOut:
    """Save the settings (admin; the router checks the role). Applies to the next message."""
    workspace_id = member.workspace_id
    before = await get_settings(db, workspace_id)
    changed = sorted(k for k, v in data.model_dump().items() if getattr(before, k) != v)
    if changed:
        prefs = await workspaces_repo.get_settings(db, workspace_id)
        prefs[SETTINGS_KEY] = {
            **data.model_dump(),
            "updated_at": now_utc().isoformat(),
            "updated_by": str(member.member.user_id),
        }
        await workspaces_repo.update_workspace(db, member.workspace, {"settings": prefs})
        await audit.record(
            db,
            workspace_id=workspace_id,
            actor_user_id=member.member.user_id,
            action="agent.settings_updated",
            target=f"workspace:{workspace_id}",
            details={"fields": changed},
        )
        await db.commit()
        await db.refresh(member.workspace)
    return await get_settings_out(db, workspace_id)


def preview(data: AgentSettings) -> AgentPreviewOut:
    """The three lines the settings change, as a worker would read them."""
    voice = voice_of(data)
    first = "1/5 Di mana lahan yang dikunjungi hari ini?"
    return AgentPreviewOut(
        after_join=copy.after_keep(voice.name, voice.style, voice.greeting),
        report_start=copy.greet(SAMPLE_SALUTATION, SAMPLE_TOPIC, first, voice.style),
        report_saved=copy.report_saved("LP-2611-0148", SAMPLE_SALUTATION, voice.style),
    )


# --- Test chat ----------------------------------------------------------------------------------


async def run_test(db: AsyncSession, workspace_id: uuid.UUID, data: AgentTestIn) -> AgentTestOut:
    """Replay the admin's test chat through the bot's engine with the settings being tried."""
    form = await forms.get_form(db, workspace_id, data.form_id)
    if form.current_version_id is None:
        raise FormNotTestable()
    version = await forms.get_version_definition(db, workspace_id, form.current_version_id)
    organization = await workspaces_repo.get_name(db, workspace_id) or ""
    tz = ZoneInfo(await workspaces_repo.get_timezone(db, workspace_id) or "Asia/Jakarta")
    voice_mode = (form.settings or {}).get("input_mode") == "voice"
    ctx = EngineContext(
        salutation=SAMPLE_SALUTATION,
        today=dt.datetime.now(tz).date(),
        topics=[Topic(str(form.id), copy.topic_title(organization, form.name))],
        definition=version.definition,
        topic_label=copy.topic_title(organization, form.name),
        voice_mode=voice_mode,
        agent=voice_of(data.settings),
    )
    reader = answers.get_answer_reader() if data.settings.read_free_answers else None

    greeting = copy.after_keep(
        data.settings.name, data.settings.style, data.settings.greeting, voice_mode
    )
    turns = [ChatTurnOut(message=None, replies=[_reply(Outbound(greeting))], events=[])]
    state = ConversationState(status="idle", topic_id=str(form.id))
    for index, sent in enumerate(data.messages):
        inbound = Inbound(text=sent.text, button=sent.button)
        step = machine.handle(state, inbound, ctx)
        events: list[str] = []
        used = None
        if step.unread is not None and sent.text and version.definition.field(step.unread):
            if sent.ai_text:
                used = sent.ai_text
            elif reader is not None:
                field = version.definition.field(step.unread)
                assert field is not None
                used = await reader.read(field, sent.text, today=ctx.today)
            if used:
                step = machine.handle(state, replace(inbound, ai_text=used), ctx)
                events.append(f"Jawaban tidak baku dibaca AI sebagai “{used}”, lalu dikonfirmasi.")
            elif data.settings.read_free_answers and reader is None:
                events.append(
                    "AI pembaca jawaban belum aktif di server, jadi agent bertanya ulang."
                )
        replies, more_events, state = _apply(step, ctx)
        turns.append(
            ChatTurnOut(
                message=index,
                replies=[_reply(r) for r in replies],
                events=events + more_events,
                ai_text=used,
            )
        )
    status = state.status if state.status in _STATUSES else "other"
    return AgentTestOut(form_name=form.name, turns=turns, status=status)  # pyright: ignore[reportArgumentType]


_STATUSES = ("idle", "asking", "confirming_summary", "submitted", "needs_help")


def _apply(step: Step, ctx: EngineContext) -> tuple[list[Outbound], list[str], ConversationState]:
    """The engine's effects, simulated: nothing is joined, stored or handed over."""
    replies = list(step.replies)
    events: list[str] = []
    state = step.state
    for effect in step.effects:
        if isinstance(effect, SubmitReport):
            replies.append(machine.report_saved(TEST_REPORT_CODE, ctx))
            events.append("Mode uji: laporan tidak disimpan.")
        elif isinstance(effect, SelectTopic):
            begun = machine.start(state, ctx)
            replies.extend(begun.replies)
            state = begun.state
        elif isinstance(effect, NeedsHelp):
            events.append("Percakapan akan diteruskan ke petugas (mode uji: tidak diteruskan).")
        elif isinstance(effect, ClaimCode):
            replies.append(Outbound("Mode uji tidak memproses kode gabung."))
    return replies, events, state


def _reply(reply: Outbound) -> ChatReplyOut:
    return ChatReplyOut(
        text=reply.text,
        buttons=[ChatButtonOut(label=b.label, value=b.value) for b in reply.buttons],
    )
