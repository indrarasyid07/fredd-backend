"""Fixtures shared by the report API tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.workspaces.models import Workspace
from tests.api.v1.reports.test_reports import Topic, _topic
from tests.conftest import sign_in


@pytest.fixture
async def topic(db: AsyncSession, organization: Workspace) -> Topic:
    """A published crop survey structure with one worker, in the `organization` workspace."""
    return await _topic(db, organization)


@pytest.fixture
async def admin(client: AsyncClient, organization: Workspace, user: User) -> AsyncClient:
    """The `client`, signed in as Dina (admin) in the `organization` workspace."""
    return await sign_in(client, user.email, organization.id)
