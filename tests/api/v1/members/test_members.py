"""ROADMAP 1.6 (part 1): list members, change role, remove; admin only; last admin protected."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.workspaces.models import Member, Workspace
from tests.conftest import add_member, sign_in

URL = "/api/v1/members"


async def _member_id(db: AsyncSession, workspace: Workspace, user: User) -> str:
    member = await db.scalar(
        select(Member).where(Member.workspace_id == workspace.id, Member.user_id == user.id)
    )
    assert member is not None
    return str(member.id)


async def test_admin_lists_members_with_names_and_roles(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await add_member(db, organization.id, email="fajar@contoh.id", role="form_editor")
    await add_member(db, organization.id, email="rani@contoh.id", role="reviewer")
    await sign_in(client, user.email, organization.id)

    body = (await client.get(URL)).json()
    assert [(m["email"], m["role"], m["status"]) for m in body["data"]] == [
        ("dina@contoh.id", "admin", "active"),
        ("fajar@contoh.id", "form_editor", "active"),
        ("rani@contoh.id", "reviewer", "active"),
    ]
    assert body["data"][0]["last_active_at"] is not None  # Dina just signed in
    assert body["meta"]["pagination"] == {"next_cursor": None, "limit": 20, "has_more": False}


async def test_list_pages_with_a_cursor(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    for n in range(3):
        await add_member(db, organization.id, email=f"p{n}@contoh.id", role="reviewer")
    await sign_in(client, user.email, organization.id)

    first = (await client.get(URL, params={"limit": 2})).json()
    assert first["meta"]["pagination"]["has_more"] is True
    second = (
        await client.get(
            URL, params={"limit": 2, "cursor": first["meta"]["pagination"]["next_cursor"]}
        )
    ).json()
    emails = [m["email"] for m in first["data"] + second["data"]]
    assert emails == ["dina@contoh.id", "p0@contoh.id", "p1@contoh.id", "p2@contoh.id"]
    assert second["meta"]["pagination"] == {"next_cursor": None, "limit": 2, "has_more": False}


async def test_broken_cursor_is_400(
    client: AsyncClient, organization: Workspace, user: User
) -> None:
    await sign_in(client, user.email, organization.id)
    response = await client.get(URL, params={"cursor": "rusak!!"})
    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "invalid_cursor"


async def test_only_admins_may_manage_members(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await add_member(db, organization.id, email="fajar@contoh.id", role="form_editor")
    await sign_in(client, "fajar@contoh.id", organization.id)
    target = await _member_id(db, organization, user)
    assert (await client.get(URL)).status_code == 403
    assert (await client.patch(f"{URL}/{target}", json={"role": "reviewer"})).status_code == 403
    assert (await client.delete(f"{URL}/{target}")).status_code == 403


async def test_change_role_and_audit(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    rani = await add_member(db, organization.id, email="rani@contoh.id", role="reviewer")
    await sign_in(client, user.email, organization.id)
    target = await _member_id(db, organization, rani)

    response = await client.patch(f"{URL}/{target}", json={"role": "form_editor"})
    assert response.status_code == 200
    roles = {m["email"]: m["role"] for m in (await client.get(URL)).json()["data"]}
    assert roles["rani@contoh.id"] == "form_editor"
    log = (await db.scalars(select(AuditLog))).one()
    assert (log.action, log.actor_user_id, log.details) == (
        "member.role_changed",
        user.id,
        {"from": "reviewer", "to": "form_editor"},
    )


async def test_unknown_role_is_422(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await sign_in(client, user.email, organization.id)
    target = await _member_id(db, organization, user)
    response = await client.patch(f"{URL}/{target}", json={"role": "owner"})
    assert response.status_code == 422


async def test_last_admin_cannot_be_demoted_or_removed(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await sign_in(client, user.email, organization.id)
    target = await _member_id(db, organization, user)
    for response in (
        await client.patch(f"{URL}/{target}", json={"role": "reviewer"}),
        await client.delete(f"{URL}/{target}"),
    ):
        assert response.status_code == 409
        assert response.json()["errors"][0]["code"] == "last_admin"


async def test_admin_can_step_down_when_another_admin_exists(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await add_member(db, organization.id, email="admin2@contoh.id", role="admin")
    await sign_in(client, user.email, organization.id)
    target = await _member_id(db, organization, user)
    assert (await client.patch(f"{URL}/{target}", json={"role": "reviewer"})).status_code == 200


async def test_remove_member_and_audit(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    rani = await add_member(db, organization.id, email="rani@contoh.id", role="reviewer")
    await sign_in(client, user.email, organization.id)
    target = await _member_id(db, organization, rani)

    assert (await client.delete(f"{URL}/{target}")).status_code == 200
    emails = [m["email"] for m in (await client.get(URL)).json()["data"]]
    assert "rani@contoh.id" not in emails
    assert (await db.scalars(select(AuditLog.action))).all() == ["member.removed"]


async def test_member_of_another_workspace_is_404(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    """Tenant isolation: a member id from another workspace looks missing."""
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    stranger = await add_member(db, other.id, email="lain@contoh.id", role="reviewer")
    await sign_in(client, user.email, organization.id)
    target = await _member_id(db, other, stranger)

    for response in (
        await client.patch(f"{URL}/{target}", json={"role": "admin"}),
        await client.delete(f"{URL}/{target}"),
    ):
        assert response.status_code == 404
        assert response.json()["errors"][0]["code"] == "member_not_found"
    emails = [m["email"] for m in (await client.get(URL)).json()["data"]]
    assert "lain@contoh.id" not in emails
