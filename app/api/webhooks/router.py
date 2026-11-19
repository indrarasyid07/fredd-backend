"""Webhooks from chat platforms: unversioned, outside /api, no standard response envelope.
CSRF does not apply (not under /api); each webhook checks its platform's signature instead."""

from fastapi import APIRouter

from app.api.webhooks import telegram

router = APIRouter(prefix="/webhooks", include_in_schema=False)
router.include_router(telegram.router)
