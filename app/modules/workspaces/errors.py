from app.core.errors import AppError, NotFound


class WorkspaceRequired(AppError):
    status_code = 400
    code = "workspace_required"
    message = "Pilih workspace terlebih dahulu."


class WorkspaceNotFound(NotFound):
    """Unknown id, or a workspace the user is not an approved member of (404, never 403)."""

    code = "workspace_not_found"
    message = "Workspace tidak ditemukan."
