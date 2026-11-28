import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

ActivityType = Literal[
    "report_received",
    "needs_help",
    "taken_over",
    "released",
    "auto_released",
    "reminder_sent",
    "draft_archived",
    "rule_alert",
]
ActivityStatus = Literal["done", "needs_review", "needs_help"]


class ActivityWorkerOut(BaseModel):
    id: uuid.UUID
    name: str


class ActivityEventOut(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    type: ActivityType
    status: ActivityStatus
    channel: Literal["telegram", "whatsapp"] | None
    # null for system events, or when the worker was removed.
    extension_worker: ActivityWorkerOut | None
    conversation_id: uuid.UUID | None
    # report_received: {report_id, code, form_name}; needs_help: {reason, field, form_name};
    # taken_over, released, auto_released: {admin_name, form_name};
    # reminder_sent: {reminder, form_name}; draft_archived: {answered, form_name};
    # rule_alert: {rule_id, rule_name, priority, form_name, code?, condition?}.
    details: dict[str, Any]
