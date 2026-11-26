from app.core.errors import AppError, NotFound


class FormNotFound(NotFound):
    """Unknown id, or a form of another workspace (404, never 403)."""

    code = "form_not_found"
    message = "Struktur data tidak ditemukan."


class FormVersionNotFound(NotFound):
    """Unknown id, a version of another workspace, or (where a published one is needed) a draft."""

    code = "form_version_not_found"
    message = "Versi struktur data tidak ditemukan."


class FormNotEditable(AppError):
    """The form has no draft version to change (published and not reopened, or archived)."""

    status_code = 409
    code = "form_not_editable"
    message = "Struktur data ini tidak sedang dalam draf, jadi tidak bisa diubah."


class FormHasProblems(AppError):
    """Publishing a draft that the automatic checks still reject (POST /forms/{id}/validate)."""

    status_code = 422
    code = "form_has_problems"

    def __init__(self, count: int) -> None:
        super().__init__(f"Perbaiki {count} masalah pada struktur data sebelum diaktifkan.")


class DraftIsTheOnlyVersion(AppError):
    """Discarding the draft of a form never published: there would be nothing left."""

    status_code = 409
    code = "draft_is_only_version"
    message = (
        "Struktur ini belum pernah diaktifkan, jadi drafnya tidak bisa dibuang. "
        "Arsipkan bila tidak dipakai."
    )


class FormArchived(AppError):
    status_code = 409
    code = "form_archived"
    message = "Struktur data ini sudah diarsipkan."
