from httpx import AsyncClient


async def test_health_reports_database_and_redis_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == {"database": "ok", "redis": "ok"}
