"""ROADMAP 1.7: the demo organization gives each demo user a different role, and reruns are safe."""

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.workspaces import service
from app.modules.workspaces.models import Workspace
from tests.conftest import PASSWORD


async def _seed(db: AsyncSession, members: list[tuple[User, str]]) -> Workspace:
    return await service.seed_organization(
        db,
        name="Fluctuz Indonesia",
        seed_key="demo",
        members=[(u.id, role) for u, role in members],  # type: ignore[misc]
    )


async def test_each_demo_user_sees_their_role(client: AsyncClient, db: AsyncSession) -> None:
    users = [
        await auth_service.create_user(db, email=f"{n}@contoh.id", name=n, password=PASSWORD)
        for n in ("dina", "fajar", "rani")
    ]
    org = await _seed(db, list(zip(users, ["admin", "form_editor", "reviewer"], strict=True)))

    for user, role in zip(users, ["admin", "form_editor", "reviewer"], strict=True):
        me = (
            await client.post(
                "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
            )
        ).json()["data"]
        [org_membership] = [m for m in me["memberships"] if m["workspace_type"] == "organization"]
        assert (org_membership["workspace_id"], org_membership["role"]) == (str(org.id), role)
        await client.post("/api/v1/auth/logout")


async def test_seed_is_idempotent_and_resets_roles(db: AsyncSession, user: User) -> None:
    first = await _seed(db, [(user, "admin")])
    second = await _seed(db, [(user, "reviewer")])
    assert first.id == second.id
    count = await db.scalar(
        select(func.count()).select_from(Workspace).where(Workspace.type == "organization")
    )
    assert count == 1
    memberships = await service.list_memberships(db, user.id)
    assert [(m.workspace_name, m.role) for m in memberships] == [
        ("Dina Admin", "admin"),
        ("Fluctuz Indonesia", "reviewer"),
    ]
