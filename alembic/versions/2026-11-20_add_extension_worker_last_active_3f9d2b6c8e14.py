"""add extension worker last active

Revision ID: 3f9d2b6c8e14
Revises: a7c29a20a105
Create Date: 2026-11-20 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f9d2b6c8e14"
down_revision: str | Sequence[str] | None = "a7c29a20a105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "extension_workers",
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_extension_workers_workspace_last_active",
        "extension_workers",
        ["workspace_id", "last_active_at"],
    )
    # Existing workers: their latest message in any conversation.
    op.execute(
        """
        update extension_workers w
        set last_active_at = c.last_at
        from (
            select extension_worker_id, max(last_inbound_at) as last_at
            from conversations group by extension_worker_id
        ) c
        where c.extension_worker_id = w.id
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_extension_workers_workspace_last_active", table_name="extension_workers")
    op.drop_column("extension_workers", "last_active_at")
