from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Session, User
from tests.conftest import PASSWORD

LOGIN = "/api/v1/auth/login"


async def test_login_sets_session_cookie_and_returns_me(
    client: AsyncClient, user: User, db: AsyncSession
) -> None:
    response = await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["message"] == "Berhasil masuk."
    assert body["data"]["user"] == {"id": str(user.id), "email": user.email, "name": user.name}
    assert body["data"]["memberships"] == []

    cookie = response.headers["set-cookie"]
    assert cookie.startswith("fluctuz_session=")
    for attribute in ("HttpOnly", "Max-Age=2592000", "Path=/", "SameSite=lax"):
        assert attribute in cookie
    sessions = await db.scalar(
        select(func.count()).select_from(Session).where(Session.user_id == user.id)
    )
    assert sessions == 1


async def test_wrong_password_and_unknown_email_look_identical(
    client: AsyncClient, user: User
) -> None:
    wrong_password = await client.post(LOGIN, json={"email": user.email, "password": "salah999"})
    unknown_email = await client.post(
        LOGIN, json={"email": "siapa@contoh.id", "password": "salah999"}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    a, b = wrong_password.json(), unknown_email.json()
    assert a["message"] == b["message"] == "Email atau kata sandi salah."
    assert (
        a["errors"]
        == b["errors"]
        == [
            {
                "code": "invalid_credentials",
                "message": "Email atau kata sandi salah.",
                "field": None,
            }
        ]
    )
    assert "set-cookie" not in wrong_password.headers


async def test_email_is_normalized(client: AsyncClient, user: User) -> None:
    response = await client.post(LOGIN, json={"email": "  DINA@Contoh.ID ", "password": PASSWORD})
    assert response.status_code == 200


async def test_sixth_failure_is_rate_limited(client: AsyncClient, user: User) -> None:
    for _ in range(5):
        response = await client.post(LOGIN, json={"email": user.email, "password": "salah999"})
        assert response.status_code == 401

    blocked = await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})

    assert blocked.status_code == 429
    assert blocked.json()["errors"][0]["code"] == "too_many_attempts"
    assert 0 < int(blocked.headers["retry-after"]) <= 15 * 60


async def test_successful_login_clears_failures(client: AsyncClient, user: User) -> None:
    for _ in range(4):
        await client.post(LOGIN, json={"email": user.email, "password": "salah999"})
    assert (
        await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})
    ).status_code == 200
    for _ in range(4):
        response = await client.post(LOGIN, json={"email": user.email, "password": "salah999"})
        assert response.status_code == 401  # counter restarted, so still not blocked
