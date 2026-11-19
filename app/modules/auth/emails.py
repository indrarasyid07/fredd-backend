"""Transactional emails of `auth`. Links point at the web app, which calls the API."""

from app.core.config import settings
from app.core.mail import Email


def _url(path: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}{path}"


def verify_email(token: str) -> Email:
    return Email(
        subject="Verifikasi email Fluctuz Anda",
        paragraphs=[
            "Terima kasih sudah mendaftar di Fluctuz. Verifikasi email Anda untuk mulai memakai "
            "akun (tautan berlaku 24 jam):"
        ],
        button_label="Verifikasi email",
        button_url=_url(f"/login/verify-email?token={token}"),
        notes=["Jika Anda tidak mendaftar, abaikan email ini."],
    )


def already_registered() -> Email:
    return Email(
        subject="Seseorang mencoba mendaftar dengan email Anda",
        paragraphs=[
            "Seseorang mencoba mendaftar di Fluctuz dengan email ini, tetapi akun sudah ada. "
            "Silakan masuk. Jika lupa kata sandi, minta tautan reset dari halaman masuk."
        ],
        button_label="Masuk ke Fluctuz",
        button_url=_url("/login"),
        notes=["Jika itu bukan Anda, abaikan email ini."],
    )


def reset_password(token: str) -> Email:
    return Email(
        subject="Atur ulang kata sandi Fluctuz",
        paragraphs=[
            "Kami menerima permintaan mengatur ulang kata sandi akun Fluctuz Anda "
            "(tautan berlaku 30 menit, sekali pakai):"
        ],
        button_label="Atur ulang kata sandi",
        button_url=_url(f"/login/reset-password?token={token}"),
        notes=["Jika Anda tidak memintanya, abaikan email ini; kata sandi Anda tidak berubah."],
    )
