"""Turn every exception into the standard error envelope."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.middleware.request_id import HEADER, current_request_id, request_id_var
from app.api.responses import ErrorItem, error_response
from app.core.errors import AppError

logger = logging.getLogger(__name__)

VALIDATION_MESSAGE = "Periksa kembali isian Anda."
INTERNAL_MESSAGE = "Terjadi kesalahan pada server. Coba lagi beberapa saat."

# Pydantic error type → (our code, Indonesian message).
_VALIDATION_CODES: dict[str, tuple[str, str]] = {
    "missing": ("required", "Wajib diisi."),
    "string_too_short": ("too_short", "Terlalu pendek."),
    "string_too_long": ("too_long", "Terlalu panjang."),
    "greater_than": ("out_of_range", "Nilai di luar rentang yang diizinkan."),
    "greater_than_equal": ("out_of_range", "Nilai di luar rentang yang diizinkan."),
    "less_than": ("out_of_range", "Nilai di luar rentang yang diizinkan."),
    "less_than_equal": ("out_of_range", "Nilai di luar rentang yang diizinkan."),
    "uuid_parsing": ("invalid_format", "Format tidak valid."),
    "enum": ("invalid_format", "Pilihan tidak valid."),
    "literal_error": ("invalid_format", "Pilihan tidak valid."),
}

_HTTP_CODES: dict[int, tuple[str, str]] = {
    404: ("not_found", "Halaman atau data tidak ditemukan."),
    405: ("method_not_allowed", "Metode tidak didukung."),
}


def _field_path(loc: tuple[str | int, ...]) -> str | None:
    # loc is ("body", "email") or ("query", "limit"); drop the location, keep the path.
    parts = [str(p) for p in loc[1:]] if loc and loc[0] in ("body", "query", "path") else []
    return ".".join(parts) or None


def _validation_item(error: dict) -> ErrorItem:
    field = _field_path(tuple(error.get("loc", ())))
    kind = error.get("type", "")
    if kind == "value_error" and "email" in str(error.get("msg", "")).lower():
        return ErrorItem(code="invalid_email", message="Format email tidak valid.", field=field)
    code, message = _VALIDATION_CODES.get(kind, ("validation_error", "Isian tidak valid."))
    return ErrorItem(code=code, message=message, field=field)


async def handle_app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    item = ErrorItem(code=exc.code, message=exc.message, field=exc.field)
    return error_response(exc.status_code, [item], exc.message, exc.headers)


async def handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = exc.errors()
    if any(e.get("type") == "json_invalid" for e in errors):
        message = "Format permintaan tidak valid."
        return error_response(400, [ErrorItem(code="bad_request", message=message)], message)
    return error_response(422, [_validation_item(e) for e in errors], VALIDATION_MESSAGE)


async def handle_http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code, message = _HTTP_CODES.get(exc.status_code, ("bad_request", "Permintaan tidak valid."))
    return error_response(exc.status_code, [ErrorItem(code=code, message=message)], message)


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Runs outside the middleware stack: restore the request's id so log, body and header match.
    request_id = getattr(request.state, "request_id", None) or current_request_id()
    request_id_var.set(request_id)
    logger.exception("unhandled error", extra={"request_id": request_id})
    item = ErrorItem(code="internal_error", message=INTERNAL_MESSAGE)
    return error_response(500, [item], INTERNAL_MESSAGE, {HEADER: request_id})


def register(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
