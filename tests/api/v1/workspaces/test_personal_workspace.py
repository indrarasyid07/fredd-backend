"""ROADMAP 1.1–1.2: every verified user owns exactly one personal workspace (D13 / B-049)."""

import re

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import service as auth_service
from app.modules.auth.google import GoogleProfile
from app.modules.auth.models import User
from app.modules.workspaces import service
from app.modules.workspaces.models import Member, Workspace
from tests.conftest import PASSWORD

SIGNUP = {
    "first_name": "Budi",
    "last_name": "Santoso",
    "email": "budi@contoh.id",
    "organization": "Dinas Pertanian",
    "password": "rahasia123",
    "accept_terms": True,
}


async def _personal(db: AsyncSession, user_id: object) -> list[tuple[Workspace, Member]]:
    rows = await db.execute(
        select(Workspace, Member)
        .join(Member, Member.workspace_id == Workspace.id)
        .where(Workspace.personal_owner_id == user_id)
    )
    return [(w, m) for w, m in rows.all()]


async def test_created_user_gets_a_personal_workspace_as_admin(
    db: AsyncSession, user: User
) -> None:
    [(workspace, member)] = await _personal(db, user.id)
    assert (workspace.type, workspace.name, workspace.timezone) == (
        "personal",
        "Dina Admin",
        "Asia/Jakarta",
    )
    assert (workspace.retention_conversations_months, workspace.retention_photos_months) == (12, 24)
    assert (member.user_id, member.role) == (user.id, "admin")
    assert member.approved_at is not None


async def test_ensure_is_idempotent(db: AsyncSession, user: User) -> None:
    first = await service.ensure_personal_workspace(db, user_id=user.id, user_name="Lain")
    second = await service.ensure_personal_workspace(db, user_id=user.id, user_name="Lain")
    assert first.id == second.id
    assert len(await _personal(db, user.id)) == 1


async def test_unverified_sign_up_has_no_workspace_until_verified(
    client: AsyncClient, db: AsyncSession, outbox: list[tuple[str, str, str]]
) -> None:
    await client.post("/api/v1/auth/register", json=SIGNUP)
    user = (await db.scalars(select(User).where(User.email == "budi@contoh.id"))).one()
    assert await _personal(db, user.id) == []

    match = re.search(r"token=([\w-]+)", outbox[-1][2])
    assert match
    response = await client.post("/api/v1/auth/verify-email", json={"token": match.group(1)})
    assert response.status_code == 200
    [(workspace, member)] = await _personal(db, user.id)
    assert (workspace.name, member.role) == ("Budi Santoso", "admin")


async def test_google_sign_up_gets_a_personal_workspace(db: AsyncSession) -> None:
    profile = GoogleProfile("sub-1", "tati@contoh.id", "Tati")
    await auth_service.login_with_google(db, profile, ip=None, user_agent=None)
    await auth_service.login_with_google(db, profile, ip=None, user_agent=None)
    user = (await db.scalars(select(User))).one()
    assert len(await _personal(db, user.id)) == 1


async def test_login_repairs_a_verified_user_without_workspace(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    await db.execute(delete(Workspace).where(Workspace.personal_owner_id == user.id))
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert response.status_code == 200
    assert len(await _personal(db, user.id)) == 1


async def test_user_may_also_belong_to_organizations(db: AsyncSession, user: User) -> None:
    """D13: a personal workspace does not stop the user from joining organizations."""
    for name in ("Dinas Pertanian Cianjur", "Dinas Pertanian Garut"):
        org = Workspace(name=name, type="organization")
        db.add(org)
        await db.flush()
        db.add(Member(workspace_id=org.id, user_id=user.id, role="reviewer"))
    await db.flush()
    count = await db.scalar(
        select(func.count()).select_from(Member).where(Member.user_id == user.id)
    )
    assert count == 3


async def test_database_allows_only_one_personal_workspace_per_user(
    db: AsyncSession, user: User
) -> None:
    db.add(Workspace(name="Kedua", type="personal", personal_owner_id=user.id))
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.parametrize(
    ("type_", "owned"),
    [("organization", True), ("personal", False), ("team", False)],
)
async def test_database_rejects_inconsistent_workspace_rows(
    db: AsyncSession, user: User, type_: str, owned: bool
) -> None:
    db.add(Workspace(name="X", type=type_, personal_owner_id=user.id if owned else None))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_database_rejects_unknown_roles(db: AsyncSession, user: User) -> None:
    [(workspace, _)] = await _personal(db, user.id)
    other = await auth_service.create_user(
        db, email="fajar@contoh.id", name="Fajar", password=PASSWORD
    )
    db.add(Member(workspace_id=workspace.id, user_id=other.id, role="owner"))
    with pytest.raises(IntegrityError):
        await db.flush()
