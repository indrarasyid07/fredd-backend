"""Opaque cursor encoding (docs/03-api/api-conventions.md#pagination). Usable from modules."""

import base64
import binascii
import json
from typing import Any

from app.core.errors import AppError


class InvalidCursor(AppError):
    status_code = 400
    code = "invalid_cursor"
    message = "Halaman data tidak valid. Muat ulang daftar dari awal."

    def __init__(self) -> None:
        super().__init__(field="cursor")


def encode_cursor(values: list[Any]) -> str:
    raw = json.dumps(values, default=str, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None, size: int) -> list[str] | None:
    """The values of the last row of the previous page, or None for the first page."""
    if cursor is None:
        return None
    try:
        values = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except binascii.Error, ValueError:
        raise InvalidCursor() from None
    if not isinstance(values, list) or len(values) != size:
        raise InvalidCursor()
    return [str(v) for v in values]
