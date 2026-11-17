from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.auth.models import Session, User

ME = "/api/v1/auth/me"
LOGOUT = "/api/v1/auth/logout"


async def test_me_with_valid_session(logged_in: AsyncClient, user: User) -> None:
    response = await logged_in.get(ME)
    assert response.status_code == 200
    assert response.json()["data"]["user"]["email"] == user.email


async def test_me_without_cookie(client: AsyncClient) -> None:
    response = await client.get(ME)
    assert response.status_code == 401
    assert response.json()["errors"][0]["code"] == "not_authenticated"


async def test_me_with_forged_cookie(client: AsyncClient) -> None:
    client.cookies.set("fluctuz_session", "forged-token-value")
    response = await client.get(ME)
    assert response.status_code == 401


async def test_me_with_expired_session(logged_in: AsyncClient, db: AsyncSession) -> None:
    await db.execute(update(Session).values(expires_at=now_utc() - timedelta(seconds=1)))
    response = await logged_in.get(ME)
    assert response.status_code == 401


async def test_logout_revokes_session(logged_in: AsyncClient) -> None:
    token = logged_in.cookies["fluctuz_session"]

    response = await logged_in.post(LOGOUT)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True and body["data"] is None
    assert 'fluctuz_session=""' in response.headers["set-cookie"]
    logged_in.cookies.set("fluctuz_session", token)  # replaying the old cookie must fail
    assert (await logged_in.get(ME)).status_code == 401


async def test_logout_without_session_still_succeeds(client: AsyncClient) -> None:
    response = await client.post(LOGOUT)
    assert response.status_code == 200
