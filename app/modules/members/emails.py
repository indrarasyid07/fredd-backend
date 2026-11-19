"""Member invite email. The link opens the web app, which calls the API."""

from app.core.config import settings
from app.core.mail import Email

ROLE_LABEL = {"admin": "Administrator", "form_editor": "Editor Struktur", "reviewer": "Peninjau"}


def invite(*, token: str, workspace_name: str, role: str, inviter: str | None) -> Email:
    who = inviter or "Administrator"
    return Email(
        subject=f"Undangan bergabung ke {workspace_name} di Fluctuz",
        paragraphs=[
            f"{who} mengundang Anda bergabung ke workspace {workspace_name} di Fluctuz "
            f"sebagai {ROLE_LABEL.get(role, role)}.",
            "Terima undangan lewat tombol di bawah (berlaku 7 hari, sekali pakai). Masuk dengan "
            "akun Google atau buat akun memakai email ini.",
        ],
        button_label="Terima undangan",
        button_url=f"{settings.app_base_url.rstrip('/')}/invite/{token}",
        notes=["Jika Anda tidak mengenal pengirimnya, abaikan email ini."],
    )
