"""Every /api/v1 feature router, with its prefix and tag, in one place."""

from fastapi import APIRouter

from app.api.v1 import auth, system

router = APIRouter(prefix="/api/v1")
router.include_router(system.router, tags=["system"])
router.include_router(auth.router, prefix="/auth", tags=["auth"])
