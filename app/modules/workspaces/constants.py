from typing import Final, Literal

WorkspaceType = Literal["personal", "organization"]
Role = Literal["admin", "form_editor", "reviewer"]

WORKSPACE_TYPES: Final = ("personal", "organization")
# Lowest to highest; require_role (Langkah 1.4) compares positions in this tuple.
ROLES: Final = ("reviewer", "form_editor", "admin")

DEFAULT_TIMEZONE: Final = "Asia/Jakarta"
# PRD §8: conversations are kept 12 months and photos 24 months unless the workspace changes it.
DEFAULT_RETENTION_CONVERSATIONS_MONTHS: Final = 12
DEFAULT_RETENTION_PHOTOS_MONTHS: Final = 24
