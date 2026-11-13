"""Every kind of response keeps the standard envelope (docs/03-api/api-conventions.md)."""

from httpx import AsyncClient

from app.main import app

ENVELOPE_KEYS = {"success", "message", "data", "errors", "meta"}


def assert_error(body: dict, code: str) -> None:
    assert set(body) == ENVELOPE_KEYS
    assert body["success"] is False
    assert body["data"] is None
    assert body["message"]
    assert body["errors"] and body["errors"][0]["code"] == code
    assert body["meta"]["request_id"] and body["meta"]["timestamp"]
    assert body["meta"]["pagination"] is None


async def test_success_envelope_and_request_id_header(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    body = response.json()
    assert set(body) == ENVELOPE_KEYS
    assert body["success"] is True and body["errors"] == []
    assert response.headers["x-request-id"] == body["meta"]["request_id"]


async def test_incoming_request_id_is_reused(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health", headers={"X-Request-ID": "caddy-1234abcd"})
    assert response.headers["x-request-id"] == "caddy-1234abcd"
    assert response.json()["meta"]["request_id"] == "caddy-1234abcd"


async def test_unknown_route_is_404_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert_error(response.json(), "not_found")


async def test_wrong_method_is_405_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/login")
    assert response.status_code == 405
    assert_error(response.json(), "method_not_allowed")


async def test_validation_errors_point_at_fields(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/login", json={"email": "bukan-email"})
    assert response.status_code == 422
    body = response.json()
    assert_error(body, body["errors"][0]["code"])
    by_field = {e["field"]: e["code"] for e in body["errors"]}
    assert by_field == {"email": "invalid_email", "password": "required"}


async def test_malformed_json_is_400(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert_error(response.json(), "bad_request")


async def test_unexpected_error_hides_details(client: AsyncClient) -> None:
    async def boom() -> None:
        raise RuntimeError("secret table name leaked")

    app.add_api_route("/api/v1/_boom", boom)
    try:
        response = await client.get("/api/v1/_boom")
    finally:
        app.router.routes.pop()
    assert response.status_code == 500
    body = response.json()
    assert_error(body, "internal_error")
    assert "secret" not in response.text
    assert response.headers["x-request-id"] == body["meta"]["request_id"]
