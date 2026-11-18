import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, Select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    # Stable constraint names keep Alembic autogenerate diffs predictable.
    metadata = MetaData(
        naming_convention={
            "ix": "%(column_0_label)s_idx",
            "uq": "%(table_name)s_%(column_0_name)s_key",
            "ck": "%(table_name)s_%(constraint_name)s_check",
            "fk": "%(table_name)s_%(column_0_name)s_fkey",
            "pk": "%(table_name)s_pkey",
        }
    )


class UUIDPrimaryKey:
    # UUID v7: unique and time-ordered, so new rows land at the end of the index.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkspaceOwned:
    """Mixin for every tenant-owned table: indexed `workspace_id`, deleted with the workspace."""

    @declared_attr
    def workspace_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)


def in_workspace[T: tuple](
    stmt: Select[T], model: type[WorkspaceOwned], workspace_id: uuid.UUID
) -> Select[T]:
    """Scope a query to one workspace. Repositories of tenant tables take `workspace_id` as a
    required argument and pass it here, so a query without a tenant filter is a visible mistake."""
    return stmt.where(model.workspace_id == workspace_id)
