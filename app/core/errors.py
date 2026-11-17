"""Base error for business rules.

Modules raise subclasses; app/api/errors.py turns them into responses.
"""


class AppError(Exception):
    status_code: int = 400
    code: str = "bad_request"
    message: str = "Permintaan tidak dapat diproses."

    def __init__(
        self,
        message: str | None = None,
        *,
        field: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or type(self).message
        self.field = field
        self.headers = headers or {}
        super().__init__(self.message)


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    message = "Data tidak ditemukan."


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    message = "Anda tidak punya akses untuk tindakan ini."


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    message = "Data bentrok dengan perubahan lain."
