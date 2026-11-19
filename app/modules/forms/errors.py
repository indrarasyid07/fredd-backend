from app.core.errors import NotFound


class FormNotFound(NotFound):
    """Unknown id, or a form of another workspace (404, never 403)."""

    code = "form_not_found"
    message = "Struktur data tidak ditemukan."


class FormVersionNotFound(NotFound):
    """Unknown id, a version of another workspace, or (where a published one is needed) a draft."""

    code = "form_version_not_found"
    message = "Versi struktur data tidak ditemukan."
