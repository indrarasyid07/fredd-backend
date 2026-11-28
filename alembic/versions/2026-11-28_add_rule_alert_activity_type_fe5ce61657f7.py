"""add rule alert activity type

Revision ID: fe5ce61657f7
Revises: 7a9266a92bc5
Create Date: 2026-11-28 13:52:41.788383

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fe5ce61657f7"
down_revision: str | Sequence[str] | None = "7a9266a92bc5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Escalation rule alerts in the activity log (roadmap 6.7)."""
    op.drop_constraint(op.f("activity_events_type_check"), "activity_events", type_="check")
    op.create_check_constraint("type", "activity_events", _types(with_alert=True))


def downgrade() -> None:
    op.execute("delete from activity_events where type = 'rule_alert'")
    op.drop_constraint(op.f("activity_events_type_check"), "activity_events", type_="check")
    op.create_check_constraint("type", "activity_events", _types(with_alert=False))


def _types(*, with_alert: bool) -> str:
    names = [
        "report_received",
        "needs_help",
        "taken_over",
        "released",
        "auto_released",
        "reminder_sent",
        "draft_archived",
    ]
    if with_alert:
        names.append("rule_alert")
    return "type in (" + ", ".join(f"'{n}'" for n in names) + ")"
