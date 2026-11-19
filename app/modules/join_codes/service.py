"""Join codes (B-048): one per data structure, created with it.

Other modules call `create_for_form` (forms, when a structure is created). The bot side
(claiming a code) comes with the conversation engine (roadmap 3.6).
"""

import secrets
import uuid
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.join_codes import errors, repository
from app.modules.join_codes.constants import ALPHABET, CLAIMABLE_FORM_STATUSES, LENGTH
from app.modules.join_codes.models import JoinCode
from app.modules.join_codes.schemas import JoinCodeOut, UpdateJoinCodeRequest


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def display(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


async def create_for_form(
    db: AsyncSession, workspace_id: uuid.UUID, form_id: uuid.UUID, user_id: uuid.UUID | None
) -> JoinCode:
    """Add the structure's code to the caller's unit of work (no commit)."""
    code = new_code()
    while await repository.code_exists(db, code):  # ~1 in 650 billion; retry anyway
        code = new_code()
    join_code = JoinCode(
        workspace_id=workspace_id,
        form_id=form_id,
        code=code,
        status="active",
        approval_mode="auto",
        created_by_user_id=user_id,
    )
    db.add(join_code)
    await db.flush()
    return join_code


async def get_for_form(
    db: AsyncSession, workspace_id: uuid.UUID, form_id: uuid.UUID, *, form_status: str
) -> JoinCodeOut:
    join_code = await repository.get_live_for_form(db, workspace_id, form_id)
    if join_code is None:
        raise errors.JoinCodeNotFound()
    return _out(join_code, form_status)


async def update_for_form(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    form_id: uuid.UUID,
    body: UpdateJoinCodeRequest,
    *,
    form_status: str,
) -> JoinCodeOut:
    join_code = await repository.get_live_for_form(db, workspace_id, form_id, for_update=True)
    if join_code is None:
        raise errors.JoinCodeNotFound()
    if body.status is not None:
        join_code.status = body.status
    if body.approval_mode is not None:
        join_code.approval_mode = body.approval_mode
    if "max_uses" in body.model_fields_set:
        join_code.max_uses = body.max_uses
    if "expires_at" in body.model_fields_set:
        join_code.expires_at = body.expires_at
    await db.commit()
    await db.refresh(join_code)
    return _out(join_code, form_status)


def _out(join_code: JoinCode, form_status: str) -> JoinCodeOut:
    shown = display(join_code.code)
    whatsapp = (
        f"https://wa.me/{settings.whatsapp_public_number}?text={quote('GABUNG ' + shown)}"
        if settings.whatsapp_public_number
        else None
    )
    telegram = (
        f"https://t.me/{settings.telegram_bot_username}?start={join_code.code}"
        if settings.telegram_bot_username
        else None
    )
    return JoinCodeOut(
        code=shown,
        status=join_code.status,  # type: ignore[arg-type]
        approval_mode=join_code.approval_mode,  # type: ignore[arg-type]
        expires_at=join_code.expires_at,
        max_uses=join_code.max_uses,
        use_count=join_code.use_count,
        claimable=join_code.status == "active" and form_status in CLAIMABLE_FORM_STATUSES,
        whatsapp_url=whatsapp,
        telegram_url=telegram,
    )
