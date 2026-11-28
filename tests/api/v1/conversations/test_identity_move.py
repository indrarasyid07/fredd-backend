"""A worker moves to a new Telegram account; history stays on the old record (roadmap 7.5)."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.extension_workers.models import ExtensionWorker
from app.modules.reports.models import Report
from app.modules.workspaces.models import Workspace
from tests.api.webhooks.test_telegram_report_flow import Worker, _answer_everything, _joined
from tests.conftest import add_member, sign_in
from tests.telegram_fixtures import FakeTelegram

NEW_ID = 999000111


class NewAccount(Worker):
    """The same person writing from a new Telegram account."""

    def __init__(self, client: AsyncClient, bot: FakeTelegram) -> None:
        super().__init__(client, bot)
        self.next_id = 530000000  # its own update ids, or the webhook drops them as repeats

    async def _send(self, update: dict[str, Any]) -> list[str]:
        for part in ("message", "callback_query"):
            if part in update:
                body = update[part]
                body["from"]["id"] = NEW_ID
                chat = body["chat"] if part == "message" else body["message"]["chat"]
                chat["id"] = NEW_ID
        return await super()._send(update)


@pytest.fixture
def old(client: AsyncClient, bot: FakeTelegram) -> Worker:
    return Worker(client, bot)


@pytest.fixture
def new(client: AsyncClient, bot: FakeTelegram) -> NewAccount:
    return NewAccount(client, bot)


async def _workers(db: AsyncSession) -> list[ExtensionWorker]:
    return list(await db.scalars(select(ExtensionWorker).order_by(ExtensionWorker.created_at)))


async def test_move_keeps_history_and_switches_the_account(
    old: Worker,
    new: NewAccount,
    db: AsyncSession,
    organization: Workspace,
    user: User,
    bot: FakeTelegram,
) -> None:
    await _joined(old, db, organization)
    await _answer_everything(old)
    await old.tap("submit")  # a report on the old account
    await old.say("mulai")  # and a draft
    await _joined(new, db, organization)  # joins again from the new phone
    first, second = await _workers(db)
    assert second.telegram_user_id == str(NEW_ID)

    await sign_in(old.client, user.email, organization.id)
    response = await old.client.post(
        f"/api/v1/extension-workers/{first.id}/move-identity",
        json={"from_extension_worker_id": str(second.id)},
    )
    assert response.status_code == 200, response.text
    (worker,) = await _workers(db)
    await db.refresh(worker)
    assert worker.id == first.id and worker.telegram_user_id == str(NEW_ID)
    assert (
        await db.scalar(
            select(func.count()).select_from(Report).where(Report.extension_worker_id == first.id)
        )
        == 1
    )
    audit = await db.scalar(
        select(AuditLog).where(AuditLog.action == "extension_worker.identity_moved")
    )
    assert audit is not None and audit.details["to"].endswith(str(NEW_ID)[-4:])

    # The new account carries on as the old record; the old account is a stranger now.
    replies = await new.say("mulai")
    assert replies  # the bot answers the new account
    before = len(bot.sent)
    await old.say("mulai")
    assert all("Survei Tanaman" not in out.text for _, out in bot.sent[before:])


async def test_move_is_admin_only_and_needs_two_records(
    old: Worker, new: NewAccount, db: AsyncSession, organization: Workspace
) -> None:
    await _joined(old, db, organization)
    await _joined(new, db, organization)
    first, second = await _workers(db)
    admin = await add_member(db, organization.id, email="rudi@example.com", role="admin")
    await sign_in(old.client, admin.email, organization.id)
    same = await old.client.post(
        f"/api/v1/extension-workers/{first.id}/move-identity",
        json={"from_extension_worker_id": str(first.id)},
    )
    assert same.status_code == 422
    assert same.json()["errors"][0]["code"] == "cannot_move_to_itself"

    reviewer = await add_member(db, organization.id, email="rina@example.com", role="reviewer")
    await sign_in(old.client, reviewer.email, organization.id)
    refused = await old.client.post(
        f"/api/v1/extension-workers/{first.id}/move-identity",
        json={"from_extension_worker_id": str(second.id)},
    )
    assert refused.status_code == 403

    other = Workspace(name="Dinas Pertanian Garut", type="organization")
    db.add(other)
    await db.flush()
    stranger = await add_member(db, other.id, email="ujang@example.com", role="admin")
    await sign_in(old.client, stranger.email, other.id)
    missing = await old.client.post(
        f"/api/v1/extension-workers/{first.id}/move-identity",
        json={"from_extension_worker_id": str(second.id)},
    )
    assert missing.status_code == 404
