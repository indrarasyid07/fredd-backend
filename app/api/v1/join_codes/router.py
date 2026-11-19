"""A structure's join code: read (any member), change approval and limits (admin).
Mounted under /forms; served by the join_codes module with the form's status from forms."""

import uuid
from typing import Any

from fastapi import APIRouter

from app.api.deps import DB, AdminMember, ReviewerMember
from app.api.responses import ApiErrorResponse, ApiResponse, ok
from app.modules.forms import service as forms
from app.modules.join_codes import service
from app.modules.join_codes.schemas import JoinCodeOut, UpdateJoinCodeRequest

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR}


@router.get("/{form_id}/join-code", response_model=ApiResponse[JoinCodeOut], responses=_GUARDS)
async def get_join_code(form_id: uuid.UUID, member: ReviewerMember, db: DB):
    form = await forms.get_form(db, member.workspace.id, form_id)
    return ok(await service.get_for_form(db, member.workspace.id, form.id, form_status=form.status))


@router.patch(
    "/{form_id}/join-code",
    response_model=ApiResponse[JoinCodeOut],
    responses={**_GUARDS, 422: _ERR},
)
async def update_join_code(
    form_id: uuid.UUID, body: UpdateJoinCodeRequest, member: AdminMember, db: DB
):
    form = await forms.get_form(db, member.workspace.id, form_id)
    code = await service.update_for_form(
        db, member.workspace.id, form.id, body, form_status=form.status
    )
    return ok(code, message="Pengaturan kode gabung disimpan.")
