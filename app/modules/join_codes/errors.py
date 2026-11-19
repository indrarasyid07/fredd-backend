from app.core.errors import NotFound


class JoinCodeNotFound(NotFound):
    code = "join_code_not_found"
    message = "Kode gabung tidak ditemukan."
