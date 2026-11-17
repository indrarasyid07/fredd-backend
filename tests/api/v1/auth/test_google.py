from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.auth import google, service
from app.modules.auth.errors import GoogleError
from app.modules.auth.google import GoogleProfile
from app.modules.auth.models import User

BASE = "/api/v1/auth/google"
LOGIN_URL = "http://localhost:3000/login"


@pytest.fixture
def google_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_client_id", "client-123")
    monkeypatch.setattr(settings, "google_client_secret", "secret")


async def test_login_without_client_id_redirects_with_unavailable(client: AsyncClient) -> None:
    response = await client.get(f"{BASE}/login")
    assert response.status_code == 303
    assert response.headers["location"] == f"{LOGIN_URL}?error=google_unavailable"


async def test_login_redirects_to_google_with_pkce_and_state_cookie(
    client: AsyncClient, google_on: None
) -> None:
    response = await client.get(f"{BASE}/login", params={"next": "/app/laporan"})

    assert response.status_code == 303
    url = urlparse(response.headers["location"])
    query = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert query["client_id"] == ["client-123"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["http://localhost:3000/api/v1/auth/google/callback"]
    assert f"fluctuz_oauth={query['state'][0]}" in response.headers["set-cookie"]


@pytest.mark.parametrize("bad", ["https://evil.example", "//evil.example", "/admin", "/app\\x"])
def test_next_must_stay_inside_the_dashboard(bad: str) -> None:
    assert google.safe_next(bad) == "/app"
    assert google.safe_next("/app/laporan") == "/app/laporan"


async def test_callback_rejects_state_that_does_not_match_the_cookie(
    client: AsyncClient, google_on: None
) -> None:
    response = await client.get(f"{BASE}/callback", params={"code": "c", "state": "forged"})
    assert response.headers["location"] == f"{LOGIN_URL}?error=google_failed"


async def test_callback_signs_in_and_redirects_to_next(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_finish(code, state, cookie_state):
        return GoogleProfile("sub-1", "tati@contoh.id", "Tati"), "/app/laporan"

    monkeypatch.setattr(google, "finish", fake_finish)
    response = await client.get(f"{BASE}/callback", params={"code": "c", "state": "s"})

    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:3000/app/laporan"
    assert "fluctuz_session=" in "; ".join(response.headers.get_list("set-cookie"))
    assert (await client.get("/api/v1/auth/me")).json()["data"]["user"]["email"] == "tati@contoh.id"


async def test_callback_with_google_error_goes_back_to_login(client: AsyncClient) -> None:
    response = await client.get(f"{BASE}/callback", params={"error": "access_denied"})
    assert response.headers["location"] == f"{LOGIN_URL}?error=google_failed"


async def test_finish_requires_a_known_state() -> None:
    with pytest.raises(GoogleError):
        await google.finish("code", "s", "s")  # never issued by start()


async def test_google_user_is_created_then_reused(db: AsyncSession) -> None:
    profile = GoogleProfile("sub-1", "tati@contoh.id", "Tati")
    await service.login_with_google(db, profile, ip=None, user_agent=None)
    await service.login_with_google(db, profile, ip=None, user_agent=None)

    users = (await db.scalars(select(User))).all()
    assert [(u.email, u.google_sub, u.password_hash is None) for u in users] == [
        ("tati@contoh.id", "sub-1", True)
    ]
    assert users[0].email_verified_at is not None


async def test_google_links_an_existing_account_by_email(db: AsyncSession, user: User) -> None:
    await service.login_with_google(
        db, GoogleProfile("sub-9", user.email, "Dina"), ip=None, user_agent=None
    )
    await db.refresh(user)
    assert user.google_sub == "sub-9" and user.password_hash is not None
    assert await db.scalar(select(func.count()).select_from(User)) == 1


async def test_linking_google_to_an_unverified_account_drops_the_squatter_password(
    client: AsyncClient, db: AsyncSession, outbox: list[tuple[str, str, str]]
) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={
            "first_name": "A",
            "last_name": "B",
            "email": "korban@contoh.id",
            "password": "milikpenyerang1",
            "accept_terms": True,
        },
    )
    await service.login_with_google(
        db, GoogleProfile("sub-7", "korban@contoh.id", "Korban"), ip=None, user_agent=None
    )
    user = (await db.scalars(select(User).where(User.email == "korban@contoh.id"))).one()
    assert user.password_hash is None and user.email_verified_at is not None
