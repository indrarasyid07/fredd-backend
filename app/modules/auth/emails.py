"""Text of the transactional emails. Links point at the web app, which calls the API."""

from app.core.config import settings


def _url(path: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}{path}"


def verify_email(token: str) -> tuple[str, str]:
    return "Verifikasi email Fredd Anda", (
        "Halo,\n\nTerima kasih sudah mendaftar di Fredd. Buka tautan ini untuk memverifikasi "
        f"email Anda (berlaku 24 jam):\n\n{_url(f'/login/verifikasi?token={token}')}\n\n"
        "Jika Anda tidak mendaftar, abaikan email ini.\n\nTim Fredd\n"
    )


def already_registered() -> tuple[str, str]:
    return "Seseorang mencoba mendaftar dengan email Anda", (
        "Halo,\n\nSeseorang mencoba mendaftar di Fredd dengan email ini, tetapi akun sudah ada. "
        f"Silakan masuk di {_url('/login')}. Jika lupa kata sandi, minta tautan reset dari "
        "halaman masuk.\n\nJika itu bukan Anda, abaikan email ini.\n\nTim Fredd\n"
    )


def reset_password(token: str) -> tuple[str, str]:
    return "Atur ulang kata sandi Fredd", (
        "Halo,\n\nKami menerima permintaan mengatur ulang kata sandi akun Fredd Anda. Buka "
        f"tautan ini (berlaku 30 menit, sekali pakai):\n\n{_url(f'/login/baru?token={token}')}"
        "\n\nJika Anda tidak memintanya, abaikan email ini; kata sandi Anda tidak berubah."
        "\n\nTim Fredd\n"
    )
