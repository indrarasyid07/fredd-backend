"""What a matched escalation rule does (roadmap 6.7), for the chat pipeline and the reminder cron.

handover → the conversation waits for an admin (`needs_help`, "Perlu ambil alih"), with the
rule's name and priority in the activity log; notify → a `rule_alert` in the activity log and
the bot carries on.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activity import service as activity
from app.modules.agent.rules_schemas import EscalationRule
from app.modules.audit import service as audit
from app.modules.channels.models import Channel
from app.modules.conversations.engine.types import ConversationState
from app.modules.conversations.models import Conversation
from app.modules.forms.models import Form


async def _record(
    db: AsyncSession, conversation: Conversation, type: str, status: str, details: dict[str, Any]
) -> None:
    channel = await db.get(Channel, conversation.channel_id)
    form = await db.get(Form, conversation.form_id)
    await activity.record(
        db,
        workspace_id=conversation.workspace_id,
        type=type,
        status=status,
        channel=channel.type if channel else None,
        extension_worker_id=conversation.extension_worker_id,
        conversation_id=conversation.id,
        details={"form_name": form.name if form else "", **details},
    )


def _rule(rule: EscalationRule) -> dict[str, Any]:
    return {"rule_id": rule.id, "rule_name": rule.name, "priority": rule.priority}


async def hand_over(
    db: AsyncSession,
    conversation: Conversation,
    rule: EscalationRule,
    *,
    field: str | None = None,
    field_label: str | None = None,
) -> None:
    """The conversation waits for an admin, like "Minta bantuan admin"."""
    state = ConversationState.from_json(conversation.state)
    state.status = "needs_help"
    conversation.state = state.to_json()
    conversation.status = "needs_help"
    conversation.next_reminder_at = None
    await audit.record(
        db,
        workspace_id=conversation.workspace_id,
        actor_user_id=None,
        action="conversation.needs_help",
        target=str(conversation.id),
        details={"reason": "rule", "rule_id": rule.id, "field": field},
    )
    await _record(
        db,
        conversation,
        "needs_help",
        "needs_help",
        {"reason": "rule", "field": field, "field_label": field_label, **_rule(rule)},
    )


async def alert(
    db: AsyncSession, conversation: Conversation, rule: EscalationRule, **details: Any
) -> None:
    """A line in the activity log for admins; the chat carries on."""
    await _record(db, conversation, "rule_alert", "needs_review", {**details, **_rule(rule)})
