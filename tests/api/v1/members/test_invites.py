"""ROADMAP 1.6 (part 2): invite by email, resend, revoke, accept the link; audit log (B-055)."""

import re
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.members.models import MemberInvite
from app.modules.workspaces.models import Member, Workspace
from tests.conftest import PASSWORD, add_member, sign_in

URL = "/api/v1/members/invites"


def _token(outbox: list[tuple[str, str, str]]) -> str:
    match = re.search(r"/invite/([\w-]+)", outbox[-1][2])
    assert match is not None
    return match.group(1)


async def _invite(client: AsyncClient, email: str = "budi@contoh.id", role: str = "reviewer"):
    return await client.post(URL, json={"email": email, "role": role})


async def _as(client: AsyncClient, email: str) -> AsyncClient:
    """Log `client` in as `email` without an active workspace (accepting needs none)."""
    client.cookies.clear()
    client.headers.pop("X-Workspace-Id", None)
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return client


async def test_admin_invites_and_the_email_carries_a_link(
    client: AsyncClient, organization: Workspace, user: User, outbox: list
) -> None:
    await sign_in(client, user.email, organization.id)

    response = await _invite(client, " Budi@Contoh.id ", "form_editor")

    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["email"], data["role"], data["status"]) == (
        "budi@contoh.id",
        "form_editor",
        "pending",
    )
    assert data["invited_by_name"] == "Dina Admin"
    to, subject, body = outbox[-1]
    assert to == "budi@contoh.id" and organization.name in subject
    assert "Editor Struktur" in body and "7 hari" in body
    listed = (await client.get(URL)).json()["data"]
    assert [i["email"] for i in listed] == ["budi@contoh.id"]


async def test_inviting_again_reissues_the_same_invite(
    client: AsyncClient, organization: Workspace, user: User, outbox: list
) -> None:
    await sign_in(client, user.email, organization.id)
    first = (await _invite(client)).json()["data"]
    old = _token(outbox)

    second = (await _invite(client, role="admin")).json()["data"]

    assert second["id"] == first["id"] and second["role"] == "admin"
    assert _token(outbox) != old
    preview = await client.post("/api/v1/invites/preview", json={"token": old})
    assert preview.json()["errors"][0]["code"] == "invite_invalid"


async def test_existing_member_cannot_be_invited(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User, outbox: list
) -> None:
    await add_member(db, organization.id, email="rani@contoh.id", role="reviewer")
    await sign_in(client, user.email, organization.id)

    response = await _invite(client, "rani@contoh.id")

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "already_member"
    assert outbox == []


async def test_personal_workspace_cannot_invite(
    client: AsyncClient, db: AsyncSession, user: User, outbox: list
) -> None:
    personal = await db.scalar(select(Workspace).where(Workspace.personal_owner_id == user.id))
    assert personal is not None
    await sign_in(client, user.email, personal.id)

    response = await _invite(client)

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "personal_workspace"


async def test_non_admins_cannot_manage_invites(
    client: AsyncClient, db: AsyncSession, organization: Workspace, outbox: list
) -> None:
    await add_member(db, organization.id, email="fajar@contoh.id", role="form_editor")
    await sign_in(client, "fajar@contoh.id", organization.id)

    assert (await _invite(client)).status_code == 403
    assert (await client.get(URL)).status_code == 403
    assert (await client.get("/api/v1/audit-logs")).status_code == 403


async def test_invite_of_another_workspace_is_404(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User, outbox: list
) -> None:
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    stranger = await add_member(db, other.id, email="admin@lain.id", role="admin")
    await sign_in(client, stranger.email, other.id)
    invite_id = (await _invite(client)).json()["data"]["id"]

    await sign_in(client, user.email, organization.id)
    assert (await client.post(f"{URL}/{invite_id}/resend")).status_code == 404
    response = await client.delete(f"{URL}/{invite_id}")
    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "invite_not_found"


async def test_resend_rotates_the_link_and_revoke_kills_it(
    client: AsyncClient, organization: Workspace, user: User, outbox: list
) -> None:
    await sign_in(client, user.email, organization.id)
    invite_id = (await _invite(client)).json()["data"]["id"]
    old = _token(outbox)

    assert (await client.post(f"{URL}/{invite_id}/resend")).status_code == 200
    new = _token(outbox)
    assert new != old
    assert (await client.post("/api/v1/invites/preview", json={"token": old})).status_code == 404

    assert (await client.delete(f"{URL}/{invite_id}")).json()["data"] is None
    assert (await client.post("/api/v1/invites/preview", json={"token": new})).status_code == 404
    assert (await client.get(URL)).json()["data"] == []


async def test_preview_works_signed_out(
    client: AsyncClient, organization: Workspace, user: User, outbox: list
) -> None:
    await sign_in(client, user.email, organization.id)
    await _invite(client, role="form_editor")
    client.cookies.clear()

    response = await client.post("/api/v1/invites/preview", json={"token": _token(outbox)})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["workspace_name"] == organization.name
    assert (data["email"], data["role"], data["invited_by_name"]) == (
        "budi@contoh.id",
        "form_editor",
        "Dina Admin",
    )


async def test_accept_joins_right_away_and_is_single_use(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User, outbox: list
) -> None:
    await sign_in(client, user.email, organization.id)
    await _invite(client, role="form_editor")
    token = _token(outbox)
    await auth_service.create_user(db, email="budi@contoh.id", name="Budi", password=PASSWORD)

    await _as(client, "budi@contoh.id")
    response = await client.post("/api/v1/invites/accept", json={"token": token})

    assert response.status_code == 200
    assert response.json()["data"] == {
        "workspace_id": str(organization.id),
        "workspace_name": organization.name,
        "role": "form_editor",
    }
    me = (await client.get("/api/v1/auth/me")).json()["data"]
    assert organization.name in [m["workspace_name"] for m in me["memberships"]]
    again = await client.post("/api/v1/invites/accept", json={"token": token})
    assert again.status_code == 404


async def test_accept_needs_the_invited_email(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User, outbox: list
) -> None:
    await sign_in(client, user.email, organization.id)
    await _invite(client)
    await auth_service.create_user(db, email="lain@contoh.id", name="Lain", password=PASSWORD)

    await _as(client, "lain@contoh.id")
    response = await client.post("/api/v1/invites/accept", json={"token": _token(outbox)})

    assert response.status_code == 403
    assert response.json()["errors"][0]["code"] == "invite_email_mismatch"


async def test_accept_needs_a_session(
    client: AsyncClient, organization: Workspace, user: User, outbox: list
) -> None:
    await sign_in(client, user.email, organization.id)
    await _invite(client)
    client.cookies.clear()

    response = await client.post("/api/v1/invites/accept", json={"token": _token(outbox)})

    assert response.status_code == 401


async def test_expired_invite_is_listed_as_expired_and_cannot_be_used(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User, outbox: list
) -> None:
    await sign_in(client, user.email, organization.id)
    await _invite(client)
    token = _token(outbox)
    await db.execute(
        update(MemberInvite).values(expires_at=MemberInvite.sent_at - timedelta(seconds=1))
    )

    assert (await client.get(URL)).json()["data"][0]["status"] == "expired"
    assert (await client.post("/api/v1/invites/preview", json={"token": token})).status_code == 404


async def test_accept_approves_a_pending_membership(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User, outbox: list
) -> None:
    budi = await auth_service.create_user(
        db, email="budi@contoh.id", name="Budi", password=PASSWORD
    )
    db.add(Member(workspace_id=organization.id, user_id=budi.id, role="reviewer"))
    await db.flush()
    await sign_in(client, user.email, organization.id)
    await _invite(client, role="admin")

    await _as(client, "budi@contoh.id")
    response = await client.post("/api/v1/invites/accept", json={"token": _token(outbox)})

    assert response.json()["data"]["role"] == "admin"


async def test_audit_log_lists_invite_actions_newest_first(
    client: AsyncClient, organization: Workspace, user: User, outbox: list
) -> None:
    await sign_in(client, user.email, organization.id)
    invite_id = (await _invite(client)).json()["data"]["id"]
    await client.delete(f"{URL}/{invite_id}")

    first = (await client.get("/api/v1/audit-logs", params={"limit": 1})).json()
    assert first["data"][0]["action"] == "member.invite_revoked"
    assert first["data"][0]["actor_name"] == "Dina Admin"
    assert first["meta"]["pagination"]["has_more"] is True
    second = (
        await client.get(
            "/api/v1/audit-logs",
            params={"limit": 1, "cursor": first["meta"]["pagination"]["next_cursor"]},
        )
    ).json()
    assert second["data"][0]["action"] == "member.invited"
    assert second["data"][0]["details"] == {"email": "budi@contoh.id", "role": "reviewer"}
    assert second["meta"]["pagination"]["has_more"] is False
