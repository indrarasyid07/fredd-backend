"""ROADMAP 1.4: require_role. reviewer < form_editor < admin; other workspaces stay 404."""

from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminMember, EditorMember, ReviewerMember
from app.api.responses import ok
from app.main import app
from app.modules.workspaces.models import Workspace
from tests.conftest import add_member, sign_in

BASE = "/api/v1/_probe/roles"


@pytest.fixture(autouse=True)
async def probes() -> AsyncIterator[None]:
    router = APIRouter()

    @router.get(f"{BASE}/reviewer")
    async def view(member: ReviewerMember):  # noqa: ANN202
        return ok({"role": member.role})

    @router.post(f"{BASE}/form_editor")
    async def edit(member: EditorMember):  # noqa: ANN202
        return ok({"role": member.role})

    @router.post(f"{BASE}/admin")
    async def manage(member: AdminMember):  # noqa: ANN202
        return ok({"role": member.role})

    before = len(app.router.routes)
    app.include_router(router)
    yield
    del app.router.routes[before:]


async def _call(client: AsyncClient, level: str) -> int:
    url = f"{BASE}/{level}"
    response = await (client.get(url) if level == "reviewer" else client.post(url))
    return response.status_code


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("reviewer", {"reviewer": 200, "form_editor": 403, "admin": 403}),
        ("form_editor", {"reviewer": 200, "form_editor": 200, "admin": 403}),
        ("admin", {"reviewer": 200, "form_editor": 200, "admin": 200}),
    ],
)
async def test_each_role_reaches_its_level_and_below(
    client: AsyncClient,
    db: AsyncSession,
    organization: Workspace,
    role: str,
    expected: dict[str, int],
) -> None:
    await add_member(db, organization.id, email=f"{role}@contoh.id", role=role)
    await sign_in(client, f"{role}@contoh.id", organization.id)
    assert {level: await _call(client, level) for level in expected} == expected


async def test_forbidden_uses_the_standard_envelope(
    client: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    await add_member(db, organization.id, email="rani@contoh.id", role="reviewer")
    await sign_in(client, "rani@contoh.id", organization.id)
    body = (await client.post(f"{BASE}/admin")).json()
    assert body["success"] is False and body["data"] is None
    assert body["errors"][0]["code"] == "forbidden"
    assert body["meta"]["request_id"]


async def test_admin_of_another_workspace_gets_404_not_403(
    client: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    """Being admin elsewhere grants nothing here, and the answer does not reveal the workspace."""
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    await add_member(db, other.id, email="lain@contoh.id", role="admin")
    await sign_in(client, "lain@contoh.id", organization.id)
    for level in ("reviewer", "form_editor", "admin"):
        assert await _call(client, level) == 404


async def test_without_session_is_401(client: AsyncClient, organization: Workspace) -> None:
    client.headers["X-Workspace-Id"] = str(organization.id)
    assert await _call(client, "reviewer") == 401
