"""The single response envelope used by every JSON endpoint. See docs/03-api/api-conventions.md."""

from datetime import datetime
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.middleware.request_id import current_request_id
from app.core.time import now_utc


class ErrorItem(BaseModel):
    code: str
    message: str
    field: str | None = None


class Pagination(BaseModel):
    next_cursor: str | None
    limit: int
    has_more: bool


class Meta(BaseModel):
    request_id: str
    timestamp: datetime
    pagination: Pagination | None = None


class ApiResponse[T](BaseModel):
    success: bool
    message: str | None
    data: T | None
    errors: list[ErrorItem]
    meta: Meta


class ApiErrorResponse(ApiResponse[None]):
    """Documents error responses in OpenAPI."""


def _meta(pagination: Pagination | None = None) -> Meta:
    return Meta(request_id=current_request_id(), timestamp=now_utc(), pagination=pagination)


def ok[T](
    data: T | None = None, *, message: str | None = None, pagination: Pagination | None = None
) -> ApiResponse[T]:
    return ApiResponse[T](
        success=True, message=message, data=data, errors=[], meta=_meta(pagination)
    )


def error_response(
    status_code: int,
    errors: list[ErrorItem],
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = ApiErrorResponse(
        success=False, message=message, data=None, errors=errors, meta=_meta()
    ).model_dump(mode="json")
    return JSONResponse(body, status_code=status_code, headers=headers)
