from httpx import AsyncClient

from app.modules.auth.models import User
from tests.conftest import PASSWORD

LOGIN = "/api/v1/auth/login"


async def test_post_from_other_site_is_rejected(client: AsyncClient, user: User) -> None:
    response = await client.post(
        LOGIN,
        json={"email": user.email, "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    body = response.json()
    assert body["errors"][0]["code"] == "csrf_rejected"
    assert response.headers["x-request-id"] == body["meta"]["request_id"]


async def test_post_without_origin_or_referer_is_rejected(client: AsyncClient, user: User) -> None:
    del client.headers["Origin"]
    response = await client.post(LOGIN, json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 403


async def test_referer_from_app_is_accepted(client: AsyncClient, user: User) -> None:
    del client.headers["Origin"]
    response = await client.post(
        LOGIN,
        json={"email": user.email, "password": PASSWORD},
        headers={"Referer": "http://localhost:3000/login?next=/app"},
    )
    assert response.status_code == 200


async def test_get_requests_are_not_checked(client: AsyncClient) -> None:
    del client.headers["Origin"]
    assert (await client.get("/api/v1/health")).status_code == 200
