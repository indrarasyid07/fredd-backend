"""Shared fixtures.

Tests use their own database (`<dev db>_test`) and Redis db 15, so development
data is never touched.
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
os.environ["REDIS_URL"] = _env["REDIS_URL"].rsplit("/", 1)[0] + "/15"
os.environ["ENVIRONMENT"] = "development"
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


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    """Capture outgoing email as (to, subject, body) instead of sending it."""
    sent: list[tuple[str, str, str]] = []

    async def fake_send(to: str, subject: str, body: str) -> None:
        sent.append((to, subject, body))

    monkeypatch.setattr(mail, "send_email", fake_send)
    return sent
