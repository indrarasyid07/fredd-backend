"""Admin approval of workers waiting on a manual join code (roadmap 4.6): the queue in the
dashboard, and what the worker hears in their chat."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.conversations.engine import copy
from app.modules.extension_workers.models import ChatContext, ExtensionWorker
from app.modules.join_codes.models import JoinCode
from app.modules.workspaces.models import Workspace
from tests.api.webhooks.test_telegram_join import CHAT, Chat, _dashed, _topic, _worker
from tests.conftest import add_member, sign_in
from tests.telegram_fixtures import FakeTelegram

URL = "/api/v1/extension-workers"


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> Chat:
    return Chat(client, bot)


async def _manual(db: AsyncSession, workspace: Workspace, name: str = "Survei Tanaman") -> JoinCode:
    code = await _topic(db, workspace, name)
    code.approval_mode = "manual"
    await db.flush()
    return code


async def _waiting(chat: Chat, db: AsyncSession, workspace: Workspace) -> ExtensionWorker:
    code = await _manual(db, workspace)
    assert await chat.say(_dashed(code)) == [copy.waiting_approval(workspace.name)]
    return await _worker(db, workspace)


async def _admin(chat: Chat, user: User, workspace: Workspace) -> AsyncClient:
    return await sign_in(chat.client, user.email, workspace.id)


async def test_queue_lists_waiting_workers_with_their_topic(
    chat: Chat, db: AsyncSession, user: User, organization: Workspace
) -> None:
    worker = await _waiting(chat, db, organization)
    api = await _admin(chat, user, organization)
    body = (await api.get(URL, params={"status": "pending_approval"})).json()
    assert body["success"] is True and body["errors"] == []
    (item,) = body["data"]
    assert item["id"] == str(worker.id)
    assert (item["name"], item["status"], item["pending_reason"]) == (
        "Budi Santoso",
        "pending_approval",
        "manual",
    )
    assert (item["channel"], item["telegram_username"]) == ("telegram", "budi_tani")
    assert item["confirmed_at"] is None
    assert item["topic"]["form_name"] == "Survei Tanaman"
    assert len(item["topic"]["join_code"]) == 9
    assert body["meta"]["pagination"] == {"next_cursor": None, "limit": 20, "has_more": False}
    assert (await api.get(URL, params={"status": "active"})).json()["data"] == []


async def test_approve_opens_the_topic_and_tells_the_worker(
    chat: Chat, db: AsyncSession, user: User, organization: Workspace
) -> None:
    worker = await _waiting(chat, db, organization)
    api = await _admin(chat, user, organization)
    before = len(chat.bot.sent)
    response = await api.post(f"{URL}/{worker.id}/approve")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "active"

    ((sent_to, out),) = chat.bot.sent[before:]
    assert sent_to == CHAT
    assert out.text.startswith("Halo Budi! Permintaan Anda sudah disetujui admin")
    assert [b.value for b in out.buttons] == ["join:keep", "join:change"]
    assert await db.scalar(select(ChatContext.active_assignment_id)) is not None
    # The usual confirmation carries on from here.
    assert await chat.tap("join:keep") == [copy.AFTER_KEEP]
    await db.refresh(worker)
    assert worker.confirmed_at is not None and worker.pending_reason is None
    count = select(func.count()).where(AuditLog.action == "extension_worker.approved")
    assert await db.scalar(count) == 1


async def test_block_says_nothing_and_closes_the_code(
    chat: Chat, db: AsyncSession, user: User, organization: Workspace
) -> None:
    worker = await _waiting(chat, db, organization)
    api = await _admin(chat, user, organization)
    before = len(chat.bot.sent)
    response = await api.post(f"{URL}/{worker.id}/block")
    assert response.status_code == 200 and response.json()["data"]["status"] == "blocked"
    assert chat.bot.sent[before:] == []
    assert await chat.say("halo") == [copy.JOIN_FIRST]
    code = await db.scalar(select(JoinCode).where(JoinCode.workspace_id == organization.id))
    assert code is not None
    assert await chat.say(_dashed(code)) == [copy.CODE_CLOSED]


async def test_approved_while_busy_keeps_the_current_topic(
    chat: Chat, db: AsyncSession, user: User, organization: Workspace
) -> None:
    worker = await _waiting(chat, db, organization)
    # Meanwhile the same person joins another organization's open topic.
    other = Workspace(name="Dinas Peternakan Garut", type="organization")
    db.add(other)
    await db.flush()
    open_code = await _topic(db, other, "Catatan Ternak")
    await chat.say(_dashed(open_code))
    busy_with = await db.scalar(select(ChatContext.active_assignment_id))

    api = await _admin(chat, user, organization)
    before = len(chat.bot.sent)
    assert (await api.post(f"{URL}/{worker.id}/approve")).status_code == 200
    ((_, out),) = chat.bot.sent[before:]
    assert out.text == copy.approved_elsewhere(organization.name, "Survei Tanaman")
    assert await db.scalar(select(ChatContext.active_assignment_id)) == busy_with


async def test_only_waiting_workers_and_only_admins(
    chat: Chat, db: AsyncSession, user: User, organization: Workspace
) -> None:
    worker = await _waiting(chat, db, organization)
    await add_member(db, organization.id, email="rani@contoh.id", role="reviewer")
    reviewer = await sign_in(chat.client, "rani@contoh.id", organization.id)
    assert (await reviewer.get(URL)).status_code == 200
    denied = await reviewer.post(f"{URL}/{worker.id}/approve")
    assert denied.status_code == 403
    assert (await reviewer.post(f"{URL}/{worker.id}/block")).status_code == 403

    api = await _admin(chat, user, organization)
    assert (await api.post(f"{URL}/{worker.id}/approve")).status_code == 200
    again = await api.post(f"{URL}/{worker.id}/block")
    assert again.status_code == 409
    assert again.json()["errors"][0]["code"] == "extension_worker_not_pending"


async def test_other_workspace_is_not_found(
    chat: Chat, db: AsyncSession, user: User, organization: Workspace
) -> None:
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    worker = await _waiting(chat, db, other)
    api = await _admin(chat, user, organization)
    response = await api.post(f"{URL}/{worker.id}/approve")
    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "extension_worker_not_found"
    assert (await api.get(URL)).json()["data"] == []


async def test_needs_a_session(client: AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401


async def test_pages_follow_the_cursor(
    client: AsyncClient, db: AsyncSession, user: User, organization: Workspace
) -> None:
    for i in range(3):
        db.add(
            ExtensionWorker(
                workspace_id=organization.id,
                name=f"Penyuluh {i}",
                telegram_user_id=f"9000{i}",
                status="pending_approval",
                pending_reason="manual",
            )
        )
        await db.flush()
    api = await sign_in(client, user.email, organization.id)
    first = (await api.get(URL, params={"limit": 2})).json()
    assert len(first["data"]) == 2 and first["meta"]["pagination"]["has_more"] is True
    cursor = first["meta"]["pagination"]["next_cursor"]
    second = (await api.get(URL, params={"limit": 2, "cursor": cursor})).json()
    assert len(second["data"]) == 1 and second["meta"]["pagination"]["has_more"] is False
    names = {w["name"] for w in first["data"] + second["data"]}
    assert names == {"Penyuluh 0", "Penyuluh 1", "Penyuluh 2"}
