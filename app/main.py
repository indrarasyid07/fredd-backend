from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import errors
from app.api.middleware.csrf import CsrfMiddleware
from app.api.middleware.request_id import RequestIdMiddleware
from app.api.router import mount
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.redis import redis
from app.db.session import engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await redis.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="Fluctuz API",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.is_development else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.is_development else None,
    )
    # Last added runs first: request id must wrap CSRF so rejections carry the id too.
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(RequestIdMiddleware)
    errors.register(app)
    mount(app)
    return app


app = create_app()
