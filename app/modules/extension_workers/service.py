"""Extension workers joining by code (B-048): one row per (organization, chat identity), one
assignment per (worker, structure), and the chat's active topic in `chat_contexts`."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import service as audit
from app.modules.extension_workers import repository
from app.modules.extension_workers.models import ChatContext, ExtensionWorker, FormAssignment


@dataclass(frozen=True)
class TelegramIdentity:
    user_id: str  # in a private chat, also the chat id
    username: str | None
    name: str | None  # from the Telegram profile


@dataclass(frozen=True)
class Joined:
    worker: ExtensionWorker
    assignment: FormAssignment
    pending_approval: bool


async def get_worker(
    db: AsyncSession, workspace_id: uuid.UUID, identity: TelegramIdentity
) -> ExtensionWorker | None:
    return await repository.get_by_telegram_user(db, workspace_id, identity.user_id)


async def join(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    form_id: uuid.UUID,
    join_code_id: uuid.UUID,
    manual_approval: bool,
    identity: TelegramIdentity,
    now: datetime,
) -> Joined:
    """Create or revive the worker and their assignment. The caller checked the code and
    counted the use; it commits."""
    worker = await repository.get_by_telegram_user(db, workspace_id, identity.user_id)
    if worker is None:
        worker = ExtensionWorker(
            workspace_id=workspace_id,
            name=identity.name or identity.username or "Penyuluh",
            name_source="channel_profile",
            telegram_user_id=identity.user_id,
            telegram_username=identity.username,
            status="pending_approval" if manual_approval else "active",
            pending_reason="manual" if manual_approval else None,
            joined_via_code_id=join_code_id,
            joined_at=now,
        )
        db.add(worker)
        await db.flush()
    elif worker.status in ("left", "unreachable"):
        worker.status = "pending_approval" if manual_approval else "active"
        worker.pending_reason = "manual" if manual_approval else None
        worker.telegram_username = identity.username or worker.telegram_username

    assignment = await repository.get_assignment(db, worker.id, form_id)
    if assignment is None:
        assignment = FormAssignment(
            workspace_id=workspace_id,
            extension_worker_id=worker.id,
            form_id=form_id,
            joined_via_code_id=join_code_id,
        )
        db.add(assignment)
        await db.flush()
    elif assignment.status != "active":
        assignment.status, assignment.left_at = "active", None
        assignment.joined_via_code_id = join_code_id

    await audit.record(
        db,
        workspace_id=workspace_id,
        actor_user_id=None,
        action="extension_worker.joined",
        target=str(worker.id),
        details={"join_code_id": str(join_code_id), "form_id": str(form_id), "channel": "telegram"},
    )
    return Joined(worker, assignment, pending_approval=worker.status == "pending_approval")


async def leave(db: AsyncSession, assignment: FormAssignment, now: datetime) -> None:
    """Drop one topic; a worker with no topic left becomes `left`."""
    assignment.status, assignment.left_at = "left", now
    await db.flush()
    if await repository.count_active_assignments(db, assignment.extension_worker_id) == 0:
        worker = await db.get(ExtensionWorker, assignment.extension_worker_id)
        if worker is not None and worker.status == "active":
            worker.status = "left"
    await audit.record(
        db,
        workspace_id=assignment.workspace_id,
        actor_user_id=None,
        action="extension_worker.left_topic",
        target=str(assignment.extension_worker_id),
        details={"form_id": str(assignment.form_id)},
    )


async def get_chat_context(
    db: AsyncSession, channel_id: uuid.UUID, chat_id: str
) -> ChatContext | None:
    return await repository.get_chat_context(db, channel_id, chat_id)


async def active_assignment(
    db: AsyncSession, channel_id: uuid.UUID, chat_id: str
) -> FormAssignment | None:
    """The chat's current topic, if it still stands."""
    context = await repository.get_chat_context(db, channel_id, chat_id)
    if context is None or context.active_assignment_id is None:
        return None
    assignment = await repository.get_assignment_by_id(db, context.active_assignment_id)
    return assignment if assignment is not None and assignment.status == "active" else None


async def set_active(
    db: AsyncSession, channel_id: uuid.UUID, chat_id: str, assignment_id: uuid.UUID | None
) -> None:
    await repository.set_chat_context(db, channel_id, chat_id, assignment_id)


async def pending_worker(db: AsyncSession, telegram_user_id: str) -> ExtensionWorker | None:
    return await repository.get_pending_by_telegram_user(db, telegram_user_id)


async def get_by_id(db: AsyncSession, worker_id: uuid.UUID) -> ExtensionWorker | None:
    return await db.get(ExtensionWorker, worker_id)
