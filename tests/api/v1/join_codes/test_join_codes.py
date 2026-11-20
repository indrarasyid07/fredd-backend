"""Join codes: one per structure, created with it, usable once the structure is open."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.audit.models import AuditLog
from app.modules.forms import service as forms
from app.modules.forms.schemas import FormDefinition
from app.modules.join_codes.models import JoinCode
from app.modules.workspaces.models import Workspace
from tests.conftest import add_member, sign_in
from tests.form_definitions import crop_survey


@pytest.fixture
async def admin(client: AsyncClient, user, organization: Workspace) -> AsyncClient:  # noqa: ANN001
    return await sign_in(client, user.email, organization.id)


async def _form(db: AsyncSession, workspace_id) -> str:  # noqa: ANN001
    form = await forms.create_form(
        db, workspace_id, None, "Survei", FormDefinition.model_validate(crop_survey())
    )
    return str(form.id)


async def test_every_new_form_gets_one_code(
    admin: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    created = await admin.post("/api/v1/forms", json={"name": "Baru"})
    form_id = created.json()["data"]["id"]
    count = await db.scalar(select(func.count()).where(JoinCode.form_id == form_id))
    assert count == 1

    data = (await admin.get(f"/api/v1/forms/{form_id}/join-code")).json()["data"]
    assert len(data["code"]) == 9 and data["code"][4] == "-"
    assert (data["status"], data["approval_mode"], data["use_count"]) == ("active", "auto", 0)
    # A draft's code exists but nobody can join yet.
    assert data["claimable"] is False


async def test_code_becomes_claimable_when_published(
    admin: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    form_id = await _form(db, organization.id)
    before = (await admin.get(f"/api/v1/forms/{form_id}/join-code")).json()["data"]
    assert (await admin.post(f"/api/v1/forms/{form_id}/publish")).status_code == 200
    after = (await admin.get(f"/api/v1/forms/{form_id}/join-code")).json()["data"]
    assert after["claimable"] is True and after["code"] == before["code"]


async def test_share_links_follow_the_bot_settings(
    admin: AsyncClient, db: AsyncSession, organization: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    form_id = await _form(db, organization.id)
    data = (await admin.get(f"/api/v1/forms/{form_id}/join-code")).json()["data"]
    assert (data["whatsapp_url"], data["telegram_url"]) == (None, None)

    monkeypatch.setattr(settings, "telegram_bot_username", "FluctuzBot")
    monkeypatch.setattr(settings, "whatsapp_public_number", "6281100000000")
    data = (await admin.get(f"/api/v1/forms/{form_id}/join-code")).json()["data"]
    raw = data["code"].replace("-", "")
    assert data["telegram_url"] == f"https://t.me/FluctuzBot?start={raw}"
    assert data["whatsapp_url"].startswith("https://wa.me/6281100000000?text=GABUNG%20")


async def test_admin_changes_approval_and_limit(
    admin: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    form_id = await _form(db, organization.id)
    url = f"/api/v1/forms/{form_id}/join-code"
    data = (await admin.patch(url, json={"approval_mode": "manual", "max_uses": 20})).json()["data"]
    assert (data["approval_mode"], data["max_uses"]) == ("manual", 20)
    data = (await admin.patch(url, json={"max_uses": None, "status": "paused"})).json()["data"]
    assert (data["max_uses"], data["status"], data["claimable"]) == (None, "paused", False)
    bad = await admin.patch(url, json={"status": "revoked"})
    assert bad.status_code == 422


async def test_roles_and_tenants(
    client: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    form_id = await _form(db, organization.id)
    await add_member(db, organization.id, email="rani@contoh.id", role="reviewer")
    reviewer = await sign_in(client, "rani@contoh.id", organization.id)
    url = f"/api/v1/forms/{form_id}/join-code"
    assert (await reviewer.get(url)).status_code == 200
    assert (await reviewer.patch(url, json={"approval_mode": "manual"})).status_code == 403

    other = Workspace(name="Lain", type="organization")
    db.add(other)
    await db.flush()
    elsewhere = await _form(db, other.id)
    assert (await reviewer.get(f"/api/v1/forms/{elsewhere}/join-code")).status_code == 404


async def test_rotate_issues_a_new_code_with_the_same_settings(
    admin: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    form_id = await _form(db, organization.id)
    url = f"/api/v1/forms/{form_id}/join-code"
    before = (
        await admin.patch(url, json={"approval_mode": "manual", "max_uses": 30, "status": "paused"})
    ).json()["data"]

    response = await admin.post(f"{url}/rotate")
    assert response.status_code == 200
    after = response.json()["data"]
    assert after["code"] != before["code"]
    assert (after["approval_mode"], after["max_uses"], after["status"]) == ("manual", 30, "paused")
    assert after["use_count"] == 0
    assert (await admin.get(url)).json()["data"]["code"] == after["code"]

    codes = (await db.scalars(select(JoinCode).where(JoinCode.form_id == form_id))).all()
    assert sorted(c.status for c in codes) == ["paused", "revoked"]
    old = next(c for c in codes if c.status == "revoked")
    assert old.revoked_at is not None
    action = await db.scalar(select(AuditLog.action).where(AuditLog.target == form_id))
    assert action == "join_code.rotated"


async def test_rotate_is_for_admins_and_own_workspace(
    client: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    form_id = await _form(db, organization.id)
    await add_member(db, organization.id, email="fajar@contoh.id", role="form_editor")
    editor = await sign_in(client, "fajar@contoh.id", organization.id)
    assert (await editor.post(f"/api/v1/forms/{form_id}/join-code/rotate")).status_code == 403

    other = Workspace(name="Lain", type="organization")
    db.add(other)
    await db.flush()
    elsewhere = await _form(db, other.id)
    admin = await sign_in(client, "dina@contoh.id", organization.id)
    assert (await admin.post(f"/api/v1/forms/{elsewhere}/join-code/rotate")).status_code == 404


async def test_bots_follow_the_environment(
    admin: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "telegram_bot_username", "FluctuzBot")
    monkeypatch.setattr(settings, "whatsapp_public_number", "")
    response = await admin.get("/api/v1/bots")
    assert response.status_code == 200
    bots = {b["type"]: b for b in response.json()["data"]}
    assert bots["telegram"] == {
        "type": "telegram", "name": "Telegram Fluctuz", "handle": "@FluctuzBot",
        "url": "https://t.me/FluctuzBot", "available": True,
    }  # fmt: skip
    assert (bots["whatsapp"]["available"], bots["whatsapp"]["url"]) == (False, None)


async def test_bots_need_a_session(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/bots")).status_code == 401
