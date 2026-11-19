"""HTTP dependencies shared by every feature router."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import read_session_token
from app.db.session import get_session
from app.modules.auth import errors as auth_errors
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.workspaces import service as workspaces_service
from app.modules.workspaces.constants import Role
from app.modules.workspaces.service import ActiveMember


async def get_db() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


DB = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(request: Request, db: DB) -> User:
    token = read_session_token(request)
    if token is None:
        raise auth_errors.NotAuthenticated()
    return await auth_service.resolve_session(db, token)


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_member(
    user: CurrentUser,
    db: DB,
    x_workspace_id: Annotated[
        str | None,
        Header(description="Workspace aktif; harus salah satu `memberships` dari /auth/me."),
    ] = None,
) -> ActiveMember:
    """Every tenant endpoint depends on this; `workspace_id` always comes from here (B-051)."""
    return await workspaces_service.get_active_member(
        db, user_id=user.id, workspace_id=x_workspace_id
    )


CurrentMember = Annotated[ActiveMember, Depends(get_current_member)]


def require_role(min_role: Role) -> Callable[[ActiveMember], Awaitable[ActiveMember]]:
    """Dependency factory: the active member, or 403 `forbidden` when the role is below `min_role`.

    Order: reviewer < form_editor < admin. A workspace the user does not belong to is still 404
    (from `get_current_member`), so the role check never reveals other workspaces.
    """

    async def dependency(member: CurrentMember) -> ActiveMember:
        return workspaces_service.check_role(member, min_role)

    return dependency


# Use in routers as `member: EditorMember`; see docs/05-security-and-access/security-model.md.
ReviewerMember = Annotated[ActiveMember, Depends(require_role("reviewer"))]
EditorMember = Annotated[ActiveMember, Depends(require_role("form_editor"))]
AdminMember = Annotated[ActiveMember, Depends(require_role("admin"))]


def client_ip(request: Request) -> str | None:
    # Behind Caddy, uvicorn --proxy-headers has already replaced this with the real client.
    return request.client.host if request.client else None
