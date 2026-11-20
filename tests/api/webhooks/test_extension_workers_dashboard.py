"""The Penyuluh screens' API (roadmap 4.4): list with filters and sorts, summary, detail, admin
edits, and blocking an active worker or unblocking one."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.conversations.engine import copy
from app.modules.extension_workers.models import ChatContext, ExtensionWorker, FormAssignment
from app.modules.reference_data.models import ReferenceData
from app.modules.workspaces.models import Workspace
from tests.api.webhooks.test_telegram_join import Chat, _dashed, _topic, _worker
from tests.conftest import add_member, sign_in
from tests.telegram_fixtures import FakeTelegram

URL = "/api/v1/extension-workers"


@pytest.fixture
def chat(client: AsyncClient, bot: FakeTelegram) -> Chat:
    return Chat(client, bot)


async def _joined(
    chat: Chat, db: AsyncSession, workspace: Workspace, topic: str = "Survei Tanaman"
):  # noqa: ANN202
    code = await _topic(db, workspace, topic)
    await chat.say(_dashed(code))
    await chat.tap("join:keep")
    return await _worker(db, workspace), code


def _worker_row(
    workspace: Workspace, name: str, user_id: str, status: str = "active"
) -> ExtensionWorker:
    return ExtensionWorker(
        workspace_id=workspace.id, name=name, telegram_user_id=user_id, status=status
    )


async def test_list_filters_and_sorts(
    client: AsyncClient, db: AsyncSession, user: User, organization: Workspace
) -> None:
    db.add_all(
        [
            _worker_row(organization, "Citra", "1"),
            _worker_row(organization, "ani", "2", "pending_approval"),
            _worker_row(organization, "Bayu", "3", "blocked"),
            ExtensionWorker(workspace_id=organization.id, name="Dewi", phone_e164="+6281100000001"),
        ]
    )
    await db.flush()
    api = await sign_in(client, user.email, organization.id)

    async def names(**params: str | list[str]) -> list[str]:
        body = (await api.get(URL, params=params)).json()
        return [w["name"] for w in body["data"]]

    assert await names(sort="name") == ["ani", "Bayu", "Citra", "Dewi"]
    assert await names(sort="name", status=["left", "blocked"]) == ["Bayu"]
    assert sorted(await names(status=["active", "pending_approval"])) == ["Citra", "Dewi", "ani"]
    assert await names(channel="whatsapp") == ["Dewi"]
    assert await names(q="ay") == ["Bayu"]

    first = (await api.get(URL, params={"sort": "name", "limit": 3})).json()
    assert [w["name"] for w in first["data"]] == ["ani", "Bayu", "Citra"]
    cursor = first["meta"]["pagination"]["next_cursor"]
    rest = (await api.get(URL, params={"sort": "name", "limit": 3, "cursor": cursor})).json()
    assert [w["name"] for w in rest["data"]] == ["Dewi"]
    assert rest["meta"]["pagination"]["has_more"] is False


async def test_last_active_follows_chat_messages(
    chat: Chat, db: AsyncSession, user: User, organization: Workspace
) -> None:
    worker, _ = await _joined(chat, db, organization)
    first = worker.last_active_at
    assert first is not None
    await chat.say("halo")
    await db.refresh(worker)
    assert worker.last_active_at is not None and worker.last_active_at > first

    db.add(_worker_row(organization, "Belum Pernah", "99"))
    await db.flush()
    api = await sign_in(chat.client, user.email, organization.id)
    body = (await api.get(URL, params={"sort": "last_active"})).json()
    assert [w["name"] for w in body["data"]] == ["Budi Santoso", "Belum Pernah"]
    assert body["data"][0]["topic_count"] == 1


async def test_summary_counts(
    chat: Chat, db: AsyncSession, user: User, organization: Workspace
) -> None:
    worker, code = await _joined(chat, db, organization)
    code.approval_mode = "manual"
    db.add_all(
        [
            _worker_row(organization, "Menunggu", "11", "pending_approval"),
            _worker_row(organization, "Keluar", "12", "left"),
            _worker_row(organization, "Diblokir", "13", "blocked"),
        ]
    )
    await db.flush()
    api = await sign_in(chat.client, user.email, organization.id)
    data = (await api.get(f"{URL}/summary")).json()["data"]
    assert data == {
        "total": 4,
        "active": 1,
        "pending_approval": 1,
        "inactive": 2,
        "new_this_week": 1,
        "manual_approval_forms": 1,
    }


async def test_detail_lists_every_topic(
    chat: Chat, db: AsyncSession, user: User, organization: Workspace
) -> None:
    worker, _ = await _joined(chat, db, organization)
    other = await _topic(db, organization, "Pantau Hama")
    await chat.say(_dashed(other))
    await chat.tap("join:switch")  # leaves Survei Tanaman

    api = await sign_in(chat.client, user.email, organization.id)
    data = (await api.get(f"{URL}/{worker.id}")).json()["data"]
    assert data["name_source"] == "channel_profile"
    assert [(t["form_name"], t["status"]) for t in data["topics"]] == [
        ("Pantau Hama", "active"),
        ("Survei Tanaman", "left"),
    ]
    assert data["topic"]["form_name"] == "Pantau Hama" and data["topic_count"] == 1


async def test_admin_edits_name_and_region(
    chat: Chat, db: AsyncSession, user: User, organization: Workspace
) -> None:
    worker, _ = await _joined(chat, db, organization)
    region = ReferenceData(type="region", value="Kabupaten Cianjur", level="regency", code="32.03")
    db.add(region)
    await db.flush()
    api = await sign_in(chat.client, user.email, organization.id)

    response = await api.patch(
        f"{URL}/{worker.id}", json={"name": "Budi S.", "region_id": str(region.id)}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["name"], data["name_source"]) == ("Budi S.", "admin")
    assert data["region"] == {"id": str(region.id), "name": "Kabupaten Cianjur"}
    count = select(func.count()).where(AuditLog.action == "extension_worker.updated")
    assert await db.scalar(count) == 1

    cleared = (await api.patch(f"{URL}/{worker.id}", json={"region_id": None})).json()["data"]
    assert cleared["region"] is None and cleared["name"] == "Budi S."

    bad = await api.patch(f"{URL}/{worker.id}", json={"region_id": str(worker.id)})
    assert bad.status_code == 422
    assert bad.json()["errors"][0]["field"] == "region_id"
    assert (await api.patch(f"{URL}/{worker.id}", json={"name": ""})).status_code == 422


async def test_block_an_active_worker_then_unblock(
    chat: Chat, db: AsyncSession, user: User, organization: Workspace
) -> None:
    worker, code = await _joined(chat, db, organization)
    api = await sign_in(chat.client, user.email, organization.id)
    before = len(chat.bot.sent)
    response = await api.post(f"{URL}/{worker.id}/block")
    assert response.status_code == 200
    assert response.json()["message"] == "Penyuluh diblokir."
    assert chat.bot.sent[before:] == []  # never told
    assert await db.scalar(select(ChatContext.active_assignment_id)) is None
    assert await db.scalar(select(FormAssignment.status)) == "left"
    # The chat lost its topic; the organization's code is closed to them.
    assert await chat.say("halo") == [copy.JOIN_FIRST]
    assert await chat.say(_dashed(code)) == [copy.CODE_CLOSED]
    again = await api.post(f"{URL}/{worker.id}/block")
    assert again.json()["errors"][0]["code"] == "extension_worker_already_blocked"

    unblocked = await api.post(f"{URL}/{worker.id}/unblock")
    assert unblocked.status_code == 200 and unblocked.json()["data"]["status"] == "left"
    replies = await chat.say(_dashed(code))
    assert replies[0].startswith("Halo Budi! Anda bergabung di")
    await db.refresh(worker)
    assert worker.status == "active"
    not_blocked = await api.post(f"{URL}/{worker.id}/unblock")
    assert not_blocked.json()["errors"][0]["code"] == "extension_worker_not_blocked"


async def test_roles_and_tenants(
    chat: Chat, db: AsyncSession, user: User, organization: Workspace
) -> None:
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    stranger, _ = await _joined(chat, db, other)
    mine = _worker_row(organization, "Milik Saya", "55")
    db.add(mine)
    await db.flush()

    await add_member(db, organization.id, email="rani@contoh.id", role="reviewer")
    reviewer = await sign_in(chat.client, "rani@contoh.id", organization.id)
    assert (await reviewer.get(f"{URL}/summary")).status_code == 200
    assert (await reviewer.get(f"{URL}/{mine.id}")).status_code == 200
    for method, path, body in [
        ("PATCH", f"{URL}/{mine.id}", {"name": "X"}),
        ("POST", f"{URL}/{mine.id}/block", None),
        ("POST", f"{URL}/{mine.id}/unblock", None),
    ]:
        assert (await reviewer.request(method, path, json=body)).status_code == 403

    api = await sign_in(chat.client, user.email, organization.id)
    for method, path in [
        ("GET", f"{URL}/{stranger.id}"),
        ("PATCH", f"{URL}/{stranger.id}"),
        ("POST", f"{URL}/{stranger.id}/block"),
    ]:
        response = await api.request(
            method, path, json={"name": "X"} if method == "PATCH" else None
        )
        assert response.status_code == 404
    names = [w["name"] for w in (await api.get(URL)).json()["data"]]
    assert names == ["Milik Saya"]
