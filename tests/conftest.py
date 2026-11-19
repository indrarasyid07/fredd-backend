"""Shared fixtures.

Tests use their own database (`<dev db>_test`) and Redis db `TEST_REDIS_DB`
(default 15), so development data is never touched. Give each worktree its own
DATABASE_URL and TEST_REDIS_DB to run test suites side by side on one machine.
Every test runs inside a transaction that is rolled back, even when the code under test commits.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from dotenv import dotenv_values

# Point the app at the test database *before* anything imports app.core.config.
_env = {**dotenv_values(Path(__file__).parents[1] / ".env"), **os.environ}
# TEST_DATABASE_URL keeps tests on a local server when DATABASE_URL points at a shared/pooled one
# (a PgBouncer pooler cannot roll each test back).
_base_db_url = _env.get("TEST_DATABASE_URL") or _env["DATABASE_URL"]
TEST_DB_NAME = _base_db_url.rsplit("/", 1)[1] + "_test"
os.environ["DATABASE_URL"] = _base_db_url.rsplit("/", 1)[0] + "/" + TEST_DB_NAME
_test_redis_db = int(_env.get("TEST_REDIS_DB") or 15)
os.environ["REDIS_URL"] = _env["REDIS_URL"].rsplit("/", 1)[0] + f"/{_test_redis_db}"
os.environ["ENVIRONMENT"] = "development"
# Jobs run inline: no worker in tests, and the outbox fixture still sees every email.
os.environ["QUEUE_INLINE"] = "true"
os.environ["APP_BASE_URL"] = "http://localhost:3000"
os.environ["ALLOWED_ORIGINS"] = ""

import asyncpg  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from alembic import command  # noqa: E402
from app.api.deps import get_db  # noqa: E402
from app.core import mail  # noqa: E402
from app.core.redis import redis  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.auth import service as auth_service  # noqa: E402
from app.modules.auth.models import User  # noqa: E402

ORIGIN = "http://localhost:3000"
PASSWORD = "rahasia123"


async def _create_test_database() -> None:
    admin_dsn = _base_db_url.replace("postgresql+asyncpg", "postgresql")
    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval("select 1 from pg_database where datname = $1", TEST_DB_NAME)
        if not exists:
            await conn.execute(f'create database "{TEST_DB_NAME}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def _migrated_test_database() -> None:
    asyncio.run(_create_test_database())
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        transaction = await conn.begin()
        session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture(autouse=True)
async def _clean_redis() -> AsyncIterator[None]:
    await redis.flushdb()
    yield


@pytest.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _test_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _test_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"Origin": ORIGIN}
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def user(db: AsyncSession) -> User:
    return await auth_service.create_user(
        db, email="dina@contoh.id", name="Dina Admin", password=PASSWORD
    )


@pytest.fixture
async def logged_in(client: AsyncClient, user: User) -> AsyncClient:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert response.status_code == 200
    return client


class Outbox(list[tuple[str, str, str]]):
    """Sent email as (to, subject, text body); `html[i]` is the HTML part of item i, or None."""

    def __init__(self) -> None:
        super().__init__()
        self.html: list[str | None] = []


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Outbox:
    """Capture outgoing email instead of sending it."""
    sent = Outbox()

    async def fake_send(to: str, subject: str, body: str, html: str | None = None) -> None:
        sent.append((to, subject, body))
        sent.html.append(html)

    monkeypatch.setattr(mail, "send_email", fake_send)
    return sent


# --- Workspaces and roles (interface 1): shared by every domain's tests ---------------------------


async def add_member(db: AsyncSession, workspace_id: object, *, email: str, role: str) -> User:
    """Create a verified user (with their own personal workspace) and add them to `workspace_id`."""
    from app.core.time import now_utc
    from app.modules.workspaces.models import Member

    member_user = await auth_service.create_user(
        db, email=email, name=email.split("@")[0].title(), password=PASSWORD
    )
    db.add(
        Member(workspace_id=workspace_id, user_id=member_user.id, role=role, approved_at=now_utc())
    )
    await db.flush()
    return member_user


async def sign_in(client: AsyncClient, email: str, workspace_id: object) -> AsyncClient:
    """Log `client` in as `email` and make `workspace_id` the active workspace for its requests."""
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    client.headers["X-Workspace-Id"] = str(workspace_id)
    return client


@pytest.fixture
async def organization(db: AsyncSession, user: User):  # noqa: ANN201
    """An organization workspace where the `user` fixture (Dina) is admin."""
    from app.core.time import now_utc
    from app.modules.workspaces.models import Member, Workspace

    org = Workspace(name="Dinas Pertanian Cianjur", type="organization")
    db.add(org)
    await db.flush()
    db.add(Member(workspace_id=org.id, user_id=user.id, role="admin", approved_at=now_utc()))
    await db.flush()
    return org
