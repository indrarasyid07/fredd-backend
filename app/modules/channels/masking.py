"""Chat identities as logs and admin screens show them (roadmap 7): enough to tell people apart,
never the whole number."""


def mask_phone(e164: str) -> str:
    """ "+6281100001234" → "+62 811-****-1234"."""
    digits = e164.lstrip("+")
    if len(digits) < 8:
        return "****"
    country, rest = digits[:2], digits[2:]
    return f"+{country} {rest[:3]}-****-{rest[-4:]}"


def mask_chat_id(chat_id: str) -> str:
    """A Telegram chat id: only the last four digits."""
    return f"•••{chat_id[-4:]}" if len(chat_id) > 4 else "••••"
