import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from fredd.config import settings
from fredd.database import engine

logger = logging.getLogger(__name__)

redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await redis.aclose()
    await engine.dispose()


is_dev = settings.environment == "development"

app = FastAPI(
    title="Fredd API",
    lifespan=lifespan,
    docs_url="/api/docs" if is_dev else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if is_dev else None,
)


@app.get("/api/v1/health")
async def health() -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        checks["database"] = "ok"
    except Exception:
        logger.exception("health: database check failed")
        checks["database"] = "error"
    try:
        await redis.ping()  # pyright: ignore[reportGeneralTypeIssues]
        checks["redis"] = "ok"
    except Exception:
        logger.exception("health: redis check failed")
        checks["redis"] = "error"

    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "degraded", "checks": checks},
        status_code=200 if ok else 503,
    )
