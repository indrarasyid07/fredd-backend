"""Every model, imported once so Alembic autogenerate sees all tables. Add each new module here."""

from app.db.base import Base
from app.modules.audit.models import AuditLog
from app.modules.auth.models import AuthToken, Session, User
from app.modules.forms.models import Form, FormTemplate, FormTemplateSector, FormVersion
from app.modules.join_codes.models import JoinCode
from app.modules.members.models import MemberInvite
from app.modules.reference_data.models import ReferenceData
from app.modules.workspaces.models import Member, Workspace

__all__ = [
    "AuditLog",
    "AuthToken",
    "Base",
    "Form",
    "FormTemplate",
    "FormTemplateSector",
    "FormVersion",
    "JoinCode",
    "Member",
    "MemberInvite",
    "ReferenceData",
    "Session",
    "User",
    "Workspace",
]
