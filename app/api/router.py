from fastapi import FastAPI

from app.api.v1.router import router as v1_router


def mount(app: FastAPI) -> None:
    app.include_router(v1_router)
    # Later: webhooks (unversioned) and devtools (development only).
