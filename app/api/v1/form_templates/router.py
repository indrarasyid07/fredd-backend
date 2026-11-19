"""The wizard's template catalogue (platform data). Served by the forms module."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import DB, ReviewerMember
from app.api.responses import ApiErrorResponse, ApiResponse, ok
from app.modules.forms import service
from app.modules.forms.schemas import FormTemplateSectorOut

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR}


@router.get("", response_model=ApiResponse[list[FormTemplateSectorOut]], responses=_GUARDS)
async def list_form_templates(_: ReviewerMember, db: DB):
    return ok(await service.list_template_catalogue(db))
