"""Text of the member invite email. The link opens the web app, which calls the API."""

from app.core.config import settings

ROLE_LABEL = {"admin": "Administrator", "form_editor": "Editor Struktur", "reviewer": "Peninjau"}


def invite(*, token: str, workspace_name: str, role: str, inviter: str | None) -> tuple[str, str]:
    who = inviter or "Administrator"
    link = f"{settings.app_base_url.rstrip('/')}/invite/{token}"
    return f"Undangan bergabung ke {workspace_name} di Fluctuz", (
        f"Halo,\n\n{who} mengundang Anda bergabung ke workspace {workspace_name} di Fluctuz "
        f"sebagai {ROLE_LABEL.get(role, role)}.\n\nBuka tautan ini untuk menerima undangan "
        f"(berlaku 7 hari, sekali pakai):\n\n{link}\n\n"
        "Masuk dengan akun Google atau buat akun memakai email ini. "
        "Jika Anda tidak mengenal pengirimnya, abaikan email ini.\n\nTim Fluctuz\n"
    )
