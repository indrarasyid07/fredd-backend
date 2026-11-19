from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import errors
from app.api.middleware.csrf import CsrfMiddleware
from app.api.middleware.request_id import RequestIdMiddleware
from app.api.openapi import include_schemas
from app.api.router import mount
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.queue import broker
from app.core.redis import redis
from app.db.session import engine
from app.modules.forms.schemas import FormDefinition


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # The API only sends jobs; the worker process starts the broker on its own.
    if not broker.is_worker_process:
        await broker.startup()
    yield
    if not broker.is_worker_process:
        await broker.shutdown()
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
    # Interface 2 (TEAM-WORKFLOW): read by the conversation engine and reports. Drop this once
    # an endpoint returns it (POST /forms/{id}/validate, roadmap 2.5).
    include_schemas(app, FormDefinition)
    return app


app = create_app()
