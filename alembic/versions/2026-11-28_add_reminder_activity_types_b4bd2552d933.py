"""add reminder activity types

Revision ID: b4bd2552d933
Revises: 59d1429402af
Create Date: 2026-11-28 11:26:03.839143

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4bd2552d933"
down_revision: str | Sequence[str] | None = "59d1429402af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Draft reminder events in the activity log (roadmap 7.1)."""
    op.drop_constraint(op.f("activity_events_type_check"), "activity_events", type_="check")
    op.create_check_constraint(
        "type",
        "activity_events",
        "type in ('report_received', 'needs_help', 'taken_over', 'released', 'auto_released', "
        "'reminder_sent', 'draft_archived')",
    )


def downgrade() -> None:
    op.execute("delete from activity_events where type in ('reminder_sent', 'draft_archived')")
    op.drop_constraint(op.f("activity_events_type_check"), "activity_events", type_="check")
    op.create_check_constraint(
        "type",
        "activity_events",
        "type in ('report_received', 'needs_help', 'taken_over', 'released', 'auto_released')",
    )
