"""add takeover activity types

Revision ID: 59d1429402af
Revises: 397d9d8430ae
Create Date: 2026-11-28 11:02:57.535352

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "59d1429402af"
down_revision: str | Sequence[str] | None = "397d9d8430ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Takeover events in the activity log (roadmap 6.4)."""
    op.drop_constraint(op.f("activity_events_type_check"), "activity_events", type_="check")
    op.create_check_constraint(
        "type",
        "activity_events",
        "type in ('report_received', 'needs_help', 'taken_over', 'released', 'auto_released')",
    )


def downgrade() -> None:
    op.execute(
        "delete from activity_events where type in ('taken_over', 'released', 'auto_released')"
    )
    op.drop_constraint(op.f("activity_events_type_check"), "activity_events", type_="check")
    op.create_check_constraint(
        "type",
        "activity_events",
        "type in ('report_received', 'needs_help')",
    )
