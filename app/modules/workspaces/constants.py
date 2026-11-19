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

# Pengaturan Umum (Langkah 1.5). Indonesia's three zones only; stored in workspaces.timezone.
TIMEZONES: Final = ("Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura")
Timezone = Literal["Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura"]
# Display preferences kept in workspaces.settings (JSONB); labels live in the frontend.
OrgType = Literal["government", "research", "company", "cooperative", "other"]
DateFormat = Literal["day_month_year", "numeric"]  # "14 Nov 2026" | "14/11/2026"
WeekStart = Literal["monday", "sunday"]
DEFAULT_DATE_FORMAT: Final = "day_month_year"
DEFAULT_WEEK_START: Final = "monday"
