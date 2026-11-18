from app.core.errors import AppError, NotFound


class MemberNotFound(NotFound):
    code = "member_not_found"
    message = "Anggota tidak ditemukan."


class LastAdmin(AppError):
    """Every workspace keeps at least one approved admin."""

    status_code = 409
    code = "last_admin"
    message = (
        "Workspace harus punya minimal satu Administrator. Jadikan anggota lain Administrator dulu."
    )
