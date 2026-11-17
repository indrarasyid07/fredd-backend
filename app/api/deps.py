"""HTTP dependencies shared by every feature router."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import read_session_token
from app.db.session import get_session
from app.modules.auth import errors as auth_errors
from app.modules.auth import service as auth_service
from app.modules.auth.models import User


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


def client_ip(request: Request) -> str | None:
    # Behind Caddy, uvicorn --proxy-headers has already replaced this with the real client.
    return request.client.host if request.client else None
