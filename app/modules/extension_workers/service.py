"""Extension workers joining by code (B-048): one row per (organization, chat identity), one
assignment per (worker, structure), and the chat's active topic in `chat_contexts`."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import InvalidCursor
from app.core.time import now_utc
from app.modules.audit import service as audit
from app.modules.extension_workers import errors, repository
from app.modules.extension_workers.models import ChatContext, ExtensionWorker, FormAssignment
from app.modules.extension_workers.repository import TopicRow
from app.modules.extension_workers.schemas import (
    ExtensionWorkerDetailOut,
    ExtensionWorkerOut,
    ExtensionWorkerSummaryOut,
    UpdateExtensionWorkerRequest,
    WorkerRegionOut,
    WorkerTopicDetailOut,
    WorkerTopicOut,
)
from app.modules.reference_data import service as reference_data


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


async def seed_demo_worker(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    form_id: uuid.UUID,
    name: str,
    phone_e164: str,
    telegram_user_id: str | None,
    region_id: uuid.UUID | None,
    joined_at: datetime,
) -> ExtensionWorker:
    """Development seed only (roadmap 4.1): an active, confirmed worker found by phone, with an
    active topic on `form_id`. Idempotent; the caller commits."""
    worker = await repository.get_by_phone(db, workspace_id, phone_e164)
    if worker is None:
        worker = ExtensionWorker(
            workspace_id=workspace_id,
            name=name,
            name_source="admin",
            phone_e164=phone_e164,
            telegram_user_id=telegram_user_id,
            region_id=region_id,
            status="active",
            joined_at=joined_at,
            confirmed_at=joined_at,
        )
        db.add(worker)
        await db.flush()
    if await repository.get_assignment(db, worker.id, form_id) is None:
        db.add(
            FormAssignment(
                workspace_id=workspace_id, extension_worker_id=worker.id, form_id=form_id
            )
        )
        await db.flush()
    return worker


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


# --- Dashboard (roadmap 4.4 and 4.6) ------------------------------------------------------------

INACTIVE = ("left", "blocked", "unreachable")


async def touch(db: AsyncSession, channel_id: uuid.UUID, chat_id: str, at: datetime) -> None:
    """The chat's worker wrote to their active topic: "Terakhir aktif"."""
    assignment = await active_assignment(db, channel_id, chat_id)
    if assignment is None:
        return
    worker = await db.get(ExtensionWorker, assignment.extension_worker_id)
    if worker is not None and (worker.last_active_at is None or worker.last_active_at < at):
        worker.last_active_at = at


def _key(sort: str, after: list[str] | None) -> tuple[Any, uuid.UUID] | None:
    """Turn a decoded cursor [sort value, id] back into its sort key."""
    if after is None:
        return None
    try:
        value: Any = after[0] if sort == "name" else datetime.fromisoformat(after[0])
        return value, uuid.UUID(after[1])
    except ValueError:
        raise InvalidCursor() from None


async def list_workers(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    statuses: list[str] | None = None,
    channel: str | None = None,
    form_id: uuid.UUID | None = None,
    query: str | None = None,
    sort: str = "newest",
    after: list[str] | None,
    limit: int,
) -> tuple[list[ExtensionWorkerOut], list[str] | None]:
    """A page of workers and the next cursor's values (None on the last page)."""
    rows = await repository.list_workers(
        db,
        workspace_id,
        statuses=statuses,
        channel=channel,
        form_id=form_id,
        query=query,
        sort=sort,
        after=_key(sort, after),
        limit=limit,
    )
    page = rows[:limit]
    more = None
    if len(rows) > limit:
        value = repository.sort_value(page[-1], sort)
        more = [value if isinstance(value, str) else value.isoformat(), str(page[-1].id)]
    return await _describe(db, workspace_id, page), more


async def summary(db: AsyncSession, workspace_id: uuid.UUID) -> ExtensionWorkerSummaryOut:
    counts = await repository.count_by_status(db, workspace_id)
    return ExtensionWorkerSummaryOut(
        total=sum(counts.values()),
        active=counts.get("active", 0),
        pending_approval=counts.get("pending_approval", 0),
        inactive=sum(counts.get(s, 0) for s in INACTIVE),
        new_this_week=await repository.count_joined_since(
            db, workspace_id, now_utc() - timedelta(days=7)
        ),
        manual_approval_forms=await repository.count_manual_approval_forms(db, workspace_id),
    )


async def describe(db: AsyncSession, worker: ExtensionWorker) -> ExtensionWorkerOut:
    return (await _describe(db, worker.workspace_id, [worker]))[0]


async def _describe(
    db: AsyncSession, workspace_id: uuid.UUID, page: list[ExtensionWorker]
) -> list[ExtensionWorkerOut]:
    ids = [w.id for w in page]
    topics = {t.worker_id: t for t in await repository.list_latest_topics(db, workspace_id, ids)}
    counts = await repository.count_topics(db, ids)
    regions = await repository.region_names(db, [w.region_id for w in page if w.region_id])
    return [_out(w, topics.get(w.id), counts.get(w.id, 0), regions) for w in page]


def _code(code: str | None) -> str | None:
    return f"{code[:4]}-{code[4:]}" if code else None


def _fields(
    worker: ExtensionWorker, topic: TopicRow | None, count: int, regions: dict[uuid.UUID, str]
) -> dict[str, Any]:
    region = (
        WorkerRegionOut(id=worker.region_id, name=regions[worker.region_id])
        if worker.region_id and worker.region_id in regions
        else None
    )
    return {
        "id": worker.id,
        "name": worker.name,
        "status": worker.status,
        "pending_reason": worker.pending_reason,
        "channel": "telegram" if worker.telegram_user_id else "whatsapp",
        "telegram_username": worker.telegram_username,
        "phone_e164": worker.phone_e164,
        "region": region,
        "joined_at": worker.joined_at,
        "confirmed_at": worker.confirmed_at,
        "last_active_at": worker.last_active_at,
        "topic": WorkerTopicOut(
            form_id=topic.form_id, form_name=topic.form_name, join_code=_code(topic.code)
        )
        if topic
        else None,
        "topic_count": count,
    }


def _out(
    worker: ExtensionWorker, topic: TopicRow | None, count: int, regions: dict[uuid.UUID, str]
) -> ExtensionWorkerOut:
    return ExtensionWorkerOut.model_validate(_fields(worker, topic, count, regions))


async def _get(db: AsyncSession, workspace_id: uuid.UUID, worker_id: uuid.UUID) -> ExtensionWorker:
    worker = await repository.get_worker(db, workspace_id, worker_id)
    if worker is None:
        raise errors.ExtensionWorkerNotFound()
    return worker


async def get_detail(
    db: AsyncSession, workspace_id: uuid.UUID, worker_id: uuid.UUID
) -> ExtensionWorkerDetailOut:
    worker = await _get(db, workspace_id, worker_id)
    topics = await repository.list_worker_topics(db, workspace_id, worker.id)
    active = [t for t in topics if t.status == "active"]
    regions = await repository.region_names(db, [worker.region_id] if worker.region_id else [])
    return ExtensionWorkerDetailOut.model_validate(
        {
            **_fields(worker, active[0] if active else None, len(active), regions),
            "name_source": worker.name_source,
            "topics": [
                WorkerTopicDetailOut(
                    form_id=t.form_id,
                    form_name=t.form_name,
                    status=t.status,  # type: ignore[arg-type]
                    join_code=_code(t.code),
                    joined_at=t.joined_at,
                    left_at=t.left_at,
                )
                for t in topics
            ],
        }
    )


async def update(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    worker_id: uuid.UUID,
    body: UpdateExtensionWorkerRequest,
    actor_user_id: uuid.UUID,
) -> ExtensionWorkerDetailOut:
    """Admin edits: a name typed in the dashboard wins over the chat profile from then on."""
    worker = await _get(db, workspace_id, worker_id)
    sent = body.model_fields_set
    changes: dict[str, Any] = {}
    if "name" in sent and body.name is not None and body.name.strip() != worker.name:
        worker.name, worker.name_source = body.name.strip(), "admin"
        changes["name"] = worker.name
    if "region_id" in sent and body.region_id != worker.region_id:
        if body.region_id is not None:
            await reference_data.get_region(db, workspace_id, body.region_id)
        worker.region_id = body.region_id
        changes["region_id"] = str(body.region_id) if body.region_id else None
    if changes:
        await audit.record(
            db,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            action="extension_worker.updated",
            target=str(worker.id),
            details=changes,
        )
    await db.commit()
    return await get_detail(db, workspace_id, worker.id)


async def approve(
    db: AsyncSession, workspace_id: uuid.UUID, worker_id: uuid.UUID, actor_user_id: uuid.UUID
) -> tuple[ExtensionWorker, FormAssignment | None]:
    """A waiting worker becomes active. Returns the topic to open in their chat (the most recent
    one). The caller tells the worker and commits."""
    worker = await _get(db, workspace_id, worker_id)
    if worker.status != "pending_approval":
        raise errors.ExtensionWorkerNotPending()
    worker.status, worker.pending_reason = "active", None
    assignments = await repository.list_active_assignments(db, worker.id)
    await audit.record(
        db,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action="extension_worker.approved",
        target=str(worker.id),
        details={},
    )
    await db.flush()
    return worker, assignments[0] if assignments else None


async def block(
    db: AsyncSession, workspace_id: uuid.UUID, worker_id: uuid.UUID, actor_user_id: uuid.UUID
) -> tuple[ExtensionWorker, bool]:
    """Refuse a waiting worker or stop an active one. The bot never tells them why: their
    topics here end, their chat loses its topic, and this organization's codes stop working for
    them. Returns the worker and whether it was a request to join rather than a member."""
    worker = await _get(db, workspace_id, worker_id)
    if worker.status == "blocked":
        raise errors.ExtensionWorkerAlreadyBlocked()
    now = now_utc()
    assignments = await repository.list_active_assignments(db, worker.id)
    for assignment in assignments:
        assignment.status, assignment.left_at = "left", now
    await repository.clear_chat_contexts(db, [a.id for a in assignments])
    previous = worker.status
    worker.status, worker.pending_reason = "blocked", None
    await audit.record(
        db,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action="extension_worker.blocked",
        target=str(worker.id),
        details={"from": previous, "topics_left": len(assignments)},
    )
    await db.commit()
    return worker, previous == "pending_approval"


async def unblock(
    db: AsyncSession, workspace_id: uuid.UUID, worker_id: uuid.UUID, actor_user_id: uuid.UUID
) -> ExtensionWorker:
    """Let a blocked worker join again: they send a code like anyone else (status `left`)."""
    worker = await _get(db, workspace_id, worker_id)
    if worker.status != "blocked":
        raise errors.ExtensionWorkerNotBlocked()
    worker.status = "left"
    await audit.record(
        db,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action="extension_worker.unblocked",
        target=str(worker.id),
        details={},
    )
    await db.commit()
    return worker
