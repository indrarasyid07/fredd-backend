from fastapi import FastAPI

from app.api.v1.router import router as v1_router
from app.api.webhooks import router as webhooks_router
from app.core.config import settings


def mount(app: FastAPI) -> None:
    app.include_router(v1_router)
    app.include_router(webhooks_router)
    if settings.is_development:
        # Never mounted elsewhere: staging and production answer 404 (roadmap 3.9).
        from app.devtools import router as devtools_router

        app.include_router(devtools_router)
