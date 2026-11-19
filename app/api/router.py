from fastapi import FastAPI

from app.api.v1.router import router as v1_router
from app.api.webhooks import router as webhooks_router


def mount(app: FastAPI) -> None:
    app.include_router(v1_router)
    app.include_router(webhooks_router)
    # Later: devtools (development only).
