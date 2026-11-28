"""Move an extension worker to a new phone or Telegram account (roadmap 7.5).

A worker with a new account joins again with the join code, which makes a second record. The
admin then moves the new identity onto the old record: the old record (its id, name, region,
reports, history) stays and takes the new account; the new record's topics, drafts and reports
join it, and the new record goes. The old account can no longer report for this organization.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import service as audit
from app.modules.channels.masking import mask_chat_id, mask_phone
from app.modules.conversations import repository
from app.modules.conversations.errors import CannotMoveToItself
from app.modules.extension_workers.errors import ExtensionWorkerNotFound
from app.modules.extension_workers.models import ExtensionWorker
from app.modules.workspaces.service import ActiveMember


def _contact(worker: ExtensionWorker) -> str:
    if worker.phone_e164:
        return mask_phone(worker.phone_e164)
    return mask_chat_id(worker.telegram_user_id or "")


async def move_identity(
    db: AsyncSession, member: ActiveMember, worker_id: uuid.UUID, from_worker_id: uuid.UUID
) -> None:
    """`worker_id` (the old record) takes the identity of `from_worker_id` (the new one)."""
    if worker_id == from_worker_id:
        raise CannotMoveToItself()
    workspace_id = member.workspace_id
    target = await repository.lock_worker(db, workspace_id, worker_id)
    source = await repository.lock_worker(db, workspace_id, from_worker_id)
    if target is None or source is None:
        raise ExtensionWorkerNotFound()
    old_contact, new_contact = _contact(target), _contact(source)
    old_chat = target.telegram_user_id or target.phone_e164

    # Topics: the new record's topics join the old one (one per structure).
    kept = {a.form_id: a for a in await repository.worker_assignments(db, target.id)}
    for assignment in await repository.worker_assignments(db, source.id):
        same = kept.get(assignment.form_id)
        conversation = await repository.get_conversation(db, source.id, assignment.form_id)
        if same is None:
            assignment.extension_worker_id = target.id
            if conversation is not None:
                conversation.extension_worker_id = target.id
            continue
        if assignment.status == "active":
            same.status, same.left_at = "active", None
        await repository.repoint_chat_contexts(db, assignment.id, same.id)
        mine = await repository.get_conversation(db, target.id, assignment.form_id)
        if conversation is not None:
            if mine is None:
                conversation.extension_worker_id = target.id
            else:
                # Two chats about one structure: the old record's draft stays, the new chat's
                # messages and reports join it.
                await repository.move_conversation_rows(db, conversation.id, mine.id)
                await db.delete(conversation)
        await db.delete(assignment)
    await db.flush()

    await repository.move_worker_rows(db, source.id, target.id)
    # The old account no longer routes to this organization's topics.
    if old_chat:
        await repository.clear_chat_contexts(db, old_chat, target.id)

    identity = (source.phone_e164, source.telegram_user_id, source.telegram_username)
    new_status = source.status
    await db.delete(source)
    await db.flush()
    target.phone_e164, target.telegram_user_id, target.telegram_username = identity
    if target.status != "blocked" and new_status in ("active", "pending_approval"):
        target.status = new_status
    new_chat = target.telegram_user_id or target.phone_e164
    if new_chat:
        await repository.point_conversations_to(db, target.id, new_chat)

    await audit.record(
        db,
        workspace_id=workspace_id,
        actor_user_id=member.member.user_id,
        action="extension_worker.identity_moved",
        target=f"extension_worker:{target.id}",
        details={"from_worker_id": str(from_worker_id), "from": old_contact, "to": new_contact},
    )
    await db.commit()
