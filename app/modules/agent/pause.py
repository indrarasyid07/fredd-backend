"""Jeda agent (roadmap 6.6, MON-04): an admin stops Fluctuz answering for the whole organization.

While paused the workers' messages are still stored and shown; each worker gets one short reply
saying so (per pause, `conversations.state["pause_notified"]` = the pause's time), draft
reminders wait and escalation rules do not run. Admins can still take a chat over. Resuming
needs nothing else: the worker's next message carries on from the open question.
Stored in `workspaces.settings["agent_pause"]` = {paused_at, paused_by}, apart from the agent
settings so saving those never undoes a pause.
"""

import datetime as dt
import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.audit import service as audit
from app.modules.auth.models import User
from app.modules.workspaces import repository as workspaces_repo
from app.modules.workspaces.service import ActiveMember

SETTINGS_KEY = "agent_pause"


class AgentStatusOut(BaseModel):
    paused: bool
    paused_at: dt.datetime | None = None
    # Name of the admin who paused it.
    paused_by: str | None = None


async def paused_since(db: AsyncSession, workspace_id: uuid.UUID) -> str | None:
    """The pause's time (ISO) when the organization's agent is paused, else None."""
    stored = (await workspaces_repo.get_settings(db, workspace_id)).get(SETTINGS_KEY) or {}
    value = stored.get("paused_at")
    return value if isinstance(value, str) else None


async def status(db: AsyncSession, workspace_id: uuid.UUID) -> AgentStatusOut:
    stored = (await workspaces_repo.get_settings(db, workspace_id)).get(SETTINGS_KEY) or {}
    at = stored.get("paused_at")
    if not isinstance(at, str):
        return AgentStatusOut(paused=False)
    by = stored.get("paused_by")
    user = await db.get(User, uuid.UUID(by)) if isinstance(by, str) else None
    return AgentStatusOut(
        paused=True, paused_at=dt.datetime.fromisoformat(at), paused_by=user.name if user else None
    )


async def set_paused(db: AsyncSession, member: ActiveMember, paused: bool) -> AgentStatusOut:
    """Pause or resume (admin). Doing it twice changes nothing."""
    prefs = await workspaces_repo.get_settings(db, member.workspace_id)
    current = prefs.get(SETTINGS_KEY) or {}
    if bool(current.get("paused_at")) != paused:
        prefs[SETTINGS_KEY] = (
            {"paused_at": now_utc().isoformat(), "paused_by": str(member.member.user_id)}
            if paused
            else {}
        )
        await workspaces_repo.update_workspace(db, member.workspace, {"settings": prefs})
        await audit.record(
            db,
            workspace_id=member.workspace_id,
            actor_user_id=member.member.user_id,
            action="agent.paused" if paused else "agent.resumed",
            target=f"workspace:{member.workspace_id}",
        )
        await db.commit()
        await db.refresh(member.workspace)
    return await status(db, member.workspace_id)
