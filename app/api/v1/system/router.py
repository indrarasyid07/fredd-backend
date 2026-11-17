import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.api.responses import ApiErrorResponse, ApiResponse, ErrorItem, error_response, ok
from app.core.redis import redis
from app.db.session import engine

logger = logging.getLogger(__name__)
router = APIRouter()


class HealthOut(BaseModel):
    database: str
    redis: str


@router.get(
    "/health", response_model=ApiResponse[HealthOut], responses={503: {"model": ApiErrorResponse}}
)
async def health():
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

    failed = [name for name, status in checks.items() if status != "ok"]
    if not failed:
        return ok(HealthOut(**checks))
    message = "Layanan sedang tidak tersedia."
    errors = [
        ErrorItem(code="service_unavailable", message=f"{name} tidak tersedia.", field=name)
        for name in failed
    ]
    response: JSONResponse = error_response(503, errors, message)
    return response
