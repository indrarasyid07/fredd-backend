"""Aturan ambil alih (roadmap 6.7): read, save and match an organization's rules.

The chat pipeline asks `keyword_rule`, `condition_rules` and `no_reply_rule`; matching is
deterministic (no language model). What a match does lives with the caller (reporting.py,
reminders.py): handover → `needs_help` with the rule's name and priority; notify → a
`rule_alert` in the activity log.
"""

import datetime as dt
import re
import uuid

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.agent.rules_schemas import (
    EscalationRule,
    EscalationRules,
    EscalationRulesOut,
    suggested_rules,
)
from app.modules.audit import service as audit
from app.modules.workspaces import repository as workspaces_repo
from app.modules.workspaces.service import ActiveMember

SETTINGS_KEY = "agent_rules"
_NOT_A_WORD = re.compile(r"[^\w]+")


def _words(text: str) -> str:
    """ " kata kata ": punctuation becomes space, so phrases match on whole words."""
    return f" {_NOT_A_WORD.sub(' ', text.lower()).strip()} "


AVAILABLE_TRIGGERS = ["keyword", "condition", "no_reply"]


async def get_rules(db: AsyncSession, workspace_id: uuid.UUID) -> list[EscalationRule]:
    stored = (await workspaces_repo.get_settings(db, workspace_id)).get(SETTINGS_KEY)
    if not stored:
        return suggested_rules()
    try:
        return EscalationRules.model_validate({"rules": stored.get("rules", [])}).rules
    except ValidationError:
        return suggested_rules()


async def get_rules_out(db: AsyncSession, workspace_id: uuid.UUID) -> EscalationRulesOut:
    stored = (await workspaces_repo.get_settings(db, workspace_id)).get(SETTINGS_KEY) or {}
    updated = stored.get("updated_at")
    return EscalationRulesOut(
        rules=await get_rules(db, workspace_id),
        updated_at=dt.datetime.fromisoformat(updated) if isinstance(updated, str) else None,
        available_triggers=AVAILABLE_TRIGGERS,
    )


async def save_rules(
    db: AsyncSession, member: ActiveMember, data: EscalationRules
) -> EscalationRulesOut:
    """Replace the whole list (admin). Applies from the next message."""
    prefs = await workspaces_repo.get_settings(db, member.workspace_id)
    prefs[SETTINGS_KEY] = {
        "rules": [r.model_dump() for r in data.rules],
        "updated_at": now_utc().isoformat(),
        "updated_by": str(member.member.user_id),
    }
    await workspaces_repo.update_workspace(db, member.workspace, {"settings": prefs})
    await audit.record(
        db,
        workspace_id=member.workspace_id,
        actor_user_id=member.member.user_id,
        action="agent.rules_updated",
        target=f"workspace:{member.workspace_id}",
        details={"enabled": [r.id for r in data.rules if r.enabled]},
    )
    await db.commit()
    await db.refresh(member.workspace)
    return await get_rules_out(db, member.workspace_id)


def keyword_rule(rules: list[EscalationRule], text: str | None) -> EscalationRule | None:
    """The first enabled keyword rule whose word or phrase is in the message (whole words)."""
    if not text:
        return None
    words = _words(text)
    for rule in rules:
        trigger = rule.trigger
        if rule.enabled and trigger.type == "keyword":
            if any(_words(k) in words for k in trigger.keywords):
                return rule
    return None


def condition_rules(rules: list[EscalationRule], condition: str | None) -> list[EscalationRule]:
    return [
        r
        for r in rules
        if r.enabled and r.trigger.type == "condition" and condition == r.trigger.equals
    ]


def no_reply_rule(rules: list[EscalationRule]) -> EscalationRule | None:
    return next((r for r in rules if r.enabled and r.trigger.type == "no_reply"), None)
