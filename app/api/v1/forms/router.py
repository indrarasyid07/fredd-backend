"""Forms (Struktur data) of the active workspace: list and read (any member), create and
autosave the draft (form_editor)."""

import uuid
from typing import Any

from fastapi import APIRouter

from app.api.deps import DB, AdminMember, EditorMember, ReviewerMember
from app.api.pagination import Cursor, Limit, decode_cursor, encode_cursor
from app.api.responses import ApiErrorResponse, ApiResponse, Pagination, ok
from app.modules.forms import service
from app.modules.forms.schemas import (
    CreateFormRequest,
    FormCheckOut,
    FormDetailOut,
    FormOut,
    UpdateFormRequest,
)

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR}


@router.get("", response_model=ApiResponse[list[FormOut]], responses=_GUARDS)
async def list_forms(member: ReviewerMember, db: DB, limit: Limit = 20, cursor: Cursor = None):
    items, more = await service.list_forms(
        db, member.workspace.id, before=decode_cursor(cursor, 1), limit=limit
    )
    next_cursor = encode_cursor([str(more)]) if more else None
    return ok(
        items,
        pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=more is not None),
    )


@router.post("", response_model=ApiResponse[FormDetailOut], responses={**_GUARDS, 422: _ERR})
async def create_form(body: CreateFormRequest, member: EditorMember, db: DB):
    form = await service.create_wizard_form(db, member.workspace.id, member.member.user_id, body)
    return ok(form, message="Draf struktur data dibuat.")


@router.get("/{form_id}", response_model=ApiResponse[FormDetailOut], responses=_GUARDS)
async def get_form(form_id: uuid.UUID, member: ReviewerMember, db: DB):
    return ok(await service.get_form_detail(db, member.workspace.id, form_id))


@router.patch(
    "/{form_id}",
    response_model=ApiResponse[FormDetailOut],
    responses={**_GUARDS, 409: _ERR, 422: _ERR},
)
async def update_form(form_id: uuid.UUID, body: UpdateFormRequest, member: EditorMember, db: DB):
    return ok(
        await service.update_form(db, member.workspace.id, form_id, body),
        message="Perubahan tersimpan.",
    )


@router.post(
    "/{form_id}/validate",
    response_model=ApiResponse[FormCheckOut],
    responses={**_GUARDS, 409: _ERR},
)
async def validate_form(form_id: uuid.UUID, member: EditorMember, db: DB):
    """Automatic checks of the draft. Problems are data, not a failed request: always 200."""
    return ok(await service.check_form(db, member.workspace.id, form_id))


@router.post(
    "/{form_id}/publish",
    response_model=ApiResponse[FormDetailOut],
    responses={**_GUARDS, 409: _ERR, 422: _ERR},
)
async def publish_form(form_id: uuid.UUID, member: AdminMember, db: DB):
    form = await service.publish_form(db, member.workspace.id, member.member.user_id, form_id)
    return ok(form, message="Struktur data aktif. Penyuluh bisa mulai melapor.")


@router.post("/{form_id}/archive", response_model=ApiResponse[FormDetailOut], responses=_GUARDS)
async def archive_form(form_id: uuid.UUID, member: AdminMember, db: DB):
    form = await service.archive_form(db, member.workspace.id, member.member.user_id, form_id)
    return ok(form, message="Struktur data diarsipkan.")
