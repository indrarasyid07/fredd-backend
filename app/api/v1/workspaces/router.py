"""The active workspace (`X-Workspace-Id`): read its settings (any member), change them (admin)."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import DB, AdminMember, ReviewerMember
from app.api.responses import ApiErrorResponse, ApiResponse, ok
from app.modules.workspaces import service
from app.modules.workspaces.schemas import UpdateWorkspaceRequest, WorkspaceOut

router = APIRouter()

_ERR = {"model": ApiErrorResponse}
_GUARDS: dict[int | str, dict[str, Any]] = {400: _ERR, 401: _ERR, 403: _ERR, 404: _ERR}


@router.get("", response_model=ApiResponse[WorkspaceOut], responses=_GUARDS)
async def get_workspace(member: ReviewerMember, db: DB):
    return ok(await service.get_settings(db, member))


@router.patch("", response_model=ApiResponse[WorkspaceOut], responses={**_GUARDS, 422: _ERR})
async def update_workspace(body: UpdateWorkspaceRequest, member: AdminMember, db: DB):
    return ok(await service.update_settings(db, member, body), message="Pengaturan disimpan.")
