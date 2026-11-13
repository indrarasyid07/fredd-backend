from app.core.errors import AppError, Conflict


class InvalidCredentials(AppError):
    status_code = 401
    code = "invalid_credentials"
    message = "Email atau kata sandi salah."


class NotAuthenticated(AppError):
    status_code = 401
    code = "not_authenticated"
    message = "Sesi Anda sudah berakhir. Silakan masuk kembali."


class TooManyAttempts(AppError):
    status_code = 429
    code = "too_many_attempts"

    def __init__(self, retry_after_seconds: int) -> None:
        minutes = max(1, -(-retry_after_seconds // 60))  # round up
        super().__init__(
            f"Terlalu banyak percobaan masuk. Coba lagi dalam {minutes} menit.",
            headers={"Retry-After": str(retry_after_seconds)},
        )


class EmailAlreadyRegistered(Conflict):
    code = "email_already_registered"
    message = "Email sudah terdaftar."


class WeakPassword(AppError):
    status_code = 422
    code = "weak_password"
    message = "Kata sandi minimal 8 karakter dan berisi huruf serta angka."
