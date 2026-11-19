"""ROADMAP 1.3: /auth/me lists memberships and X-Workspace-Id picks the active one (B-051)."""

from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentMember
from app.api.responses import ok
from app.core.time import now_utc
from app.main import app
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.workspaces.models import Member, Workspace
from tests.conftest import PASSWORD

PROBE = "/api/v1/_probe/active-workspace"


@pytest.fixture
async def probe() -> AsyncIterator[None]:
    """A throwaway tenant endpoint, until real ones (forms, reports) exist."""
    router = APIRouter()

    @router.get(PROBE)
    async def active(member: CurrentMember):  # noqa: ANN202
        return ok({"workspace_id": str(member.workspace_id), "role": member.role})

    before = len(app.router.routes)
    app.include_router(router)
    yield
    del app.router.routes[before:]


async def _organization(
    db: AsyncSession, user: User, name: str, role: str, *, approved: bool = True
) -> Workspace:
    org = Workspace(name=name, type="organization")
    db.add(org)
    await db.flush()
    db.add(
        Member(
            workspace_id=org.id,
            user_id=user.id,
            role=role,
            approved_at=now_utc() if approved else None,
        )
    )
    await db.flush()
    return org


async def test_me_lists_personal_first_then_organizations(
    logged_in: AsyncClient, db: AsyncSession, user: User
) -> None:
    await _organization(db, user, "Dinas Pertanian Garut", "reviewer")
    await _organization(db, user, "Dinas Pertanian Cianjur", "form_editor")
    await _organization(db, user, "BPP Sukaresmi", "admin", approved=False)

    response = await logged_in.get("/api/v1/auth/me")
    memberships = response.json()["data"]["memberships"]
    assert [(m["workspace_name"], m["workspace_type"], m["role"]) for m in memberships] == [
        ("Dina Admin", "personal", "admin"),
        ("Dinas Pertanian Cianjur", "organization", "form_editor"),
        ("Dinas Pertanian Garut", "organization", "reviewer"),
    ]


async def test_me_without_membership_returns_empty_list(
    logged_in: AsyncClient, db: AsyncSession, user: User
) -> None:
    await db.execute(delete(Workspace).where(Workspace.personal_owner_id == user.id))
    response = await logged_in.get("/api/v1/auth/me")
    assert response.json()["data"]["memberships"] == []


async def test_header_selects_the_workspace_and_role(
    logged_in: AsyncClient, db: AsyncSession, user: User, probe: None
) -> None:
    org = await _organization(db, user, "Dinas Pertanian Cianjur", "reviewer")
    response = await logged_in.get(PROBE, headers={"X-Workspace-Id": str(org.id)})
    assert response.status_code == 200
    assert response.json()["data"] == {"workspace_id": str(org.id), "role": "reviewer"}


async def test_missing_header_is_rejected(logged_in: AsyncClient, probe: None) -> None:
    response = await logged_in.get(PROBE)
    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "workspace_required"


@pytest.mark.parametrize("value", ["bukan-uuid", "0190d5a4-0000-7000-8000-000000000000"])
async def test_unknown_workspace_is_not_found(
    logged_in: AsyncClient, probe: None, value: str
) -> None:
    response = await logged_in.get(PROBE, headers={"X-Workspace-Id": value})
    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "workspace_not_found"


async def test_other_users_workspace_is_not_found(
    logged_in: AsyncClient, db: AsyncSession, probe: None
) -> None:
    """Tenant isolation: someone else's workspace looks exactly like a missing one."""
    other = await auth_service.create_user(
        db, email="rani@contoh.id", name="Rani", password=PASSWORD
    )
    org = await _organization(db, other, "Dinas Lain", "admin")
    for workspace_id in (
        org.id,
        (await auth_service.get_me(db, other)).memberships[0].workspace_id,
    ):
        response = await logged_in.get(PROBE, headers={"X-Workspace-Id": str(workspace_id)})
        assert response.status_code == 404


async def test_pending_membership_grants_nothing(
    logged_in: AsyncClient, db: AsyncSession, user: User, probe: None
) -> None:
    org = await _organization(db, user, "BPP Sukaresmi", "admin", approved=False)
    response = await logged_in.get(PROBE, headers={"X-Workspace-Id": str(org.id)})
    assert response.status_code == 404


async def test_header_needs_a_session(client: AsyncClient, probe: None) -> None:
    response = await client.get(PROBE, headers={"X-Workspace-Id": "x"})
    assert response.status_code == 401
