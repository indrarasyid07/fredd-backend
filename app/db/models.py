"""Every model, imported once so Alembic autogenerate sees all tables. Add each new module here."""

from app.db.base import Base
from app.modules.audit.models import AuditLog
from app.modules.auth.models import AuthToken, Session, User
from app.modules.workspaces.models import Member, Workspace

__all__ = ["AuditLog", "AuthToken", "Base", "Member", "Session", "User", "Workspace"]
