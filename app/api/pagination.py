"""Query parameters shared by every list endpoint."""

from typing import Annotated

from fastapi import Query

from app.core.pagination import decode_cursor, encode_cursor

Limit = Annotated[int, Query(ge=1, le=100, description="Jumlah baris per halaman (maks. 100).")]
Cursor = Annotated[str | None, Query(description="`next_cursor` dari halaman sebelumnya.")]

__all__ = ["Cursor", "Limit", "decode_cursor", "encode_cursor"]
