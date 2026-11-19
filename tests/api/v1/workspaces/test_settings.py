"""ROADMAP 1.5: GET/PATCH /workspace for the active workspace (any member reads, admin writes)."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.workspaces.models import Workspace
from tests.conftest import add_member, sign_in

URL = "/api/v1/workspace"


async def test_member_reads_settings_with_defaults(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await add_member(db, organization.id, email="rani@contoh.id", role="reviewer")
    await sign_in(client, "rani@contoh.id", organization.id)

    data = (await client.get(URL)).json()["data"]

    assert data["name"] == organization.name and data["type"] == "organization"
    assert (data["timezone"], data["date_format"], data["week_start"]) == (
        "Asia/Jakarta",
        "day_month_year",
        "monday",
    )
    assert data["org_type"] is None and data["quiet_hours"] is None
    assert (data["retention_conversations_months"], data["retention_photos_months"]) == (12, 24)
    assert data["member_count"] == 2


async def test_admin_updates_only_given_fields(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    organization.settings = {"seed_key": "keep-me"}
    await db.flush()
    await sign_in(client, user.email, organization.id)

    response = await client.patch(
        URL,
        json={
            "name": "  Dinas Pertanian Garut  ",
            "org_type": "government",
            "timezone": "Asia/Makassar",
            "week_start": "sunday",
            "quiet_hours": {"start": "21:00", "end": "06:00"},
            "operating_hours": {"days": [1, 2, 3, 4, 5], "start": "07:00", "end": "16:00"},
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["name"] == "Dinas Pertanian Garut"
    assert (data["org_type"], data["timezone"], data["week_start"]) == (
        "government",
        "Asia/Makassar",
        "sunday",
    )
    assert data["date_format"] == "day_month_year"  # untouched
    assert data["quiet_hours"] == {"start": "21:00", "end": "06:00"}
    await db.refresh(organization)
    assert organization.settings["seed_key"] == "keep-me"
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "workspace.updated"))
    assert entry is not None
    assert entry.details["fields"] == [
        "name",
        "operating_hours",
        "quiet_hours",
        "settings",
        "timezone",
    ]


async def test_null_clears_quiet_hours(
    client: AsyncClient, organization: Workspace, user: User
) -> None:
    await sign_in(client, user.email, organization.id)
    await client.patch(URL, json={"quiet_hours": {"start": "21:00", "end": "06:00"}})

    data = (await client.patch(URL, json={"quiet_hours": None})).json()["data"]

    assert data["quiet_hours"] is None


async def test_no_change_writes_no_audit_entry(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    await sign_in(client, user.email, organization.id)

    assert (await client.patch(URL, json={"name": organization.name})).status_code == 200

    assert await db.scalar(select(AuditLog).where(AuditLog.action == "workspace.updated")) is None


async def test_invalid_values_are_422_with_field(
    client: AsyncClient, organization: Workspace, user: User
) -> None:
    await sign_in(client, user.email, organization.id)

    for body, field in [
        ({"name": "   "}, "name"),
        ({"timezone": "Europe/Paris"}, "timezone"),
        ({"quiet_hours": {"start": "25:00", "end": "06:00"}}, "quiet_hours.start"),
        ({"quiet_hours": {"start": "06:00", "end": "06:00"}}, "quiet_hours"),
        (
            {"operating_hours": {"days": [8], "start": "07:00", "end": "16:00"}},
            "operating_hours.days.0",
        ),
        ({"retention_photos_months": 0}, "retention_photos_months"),
    ]:
        response = await client.patch(URL, json=body)
        assert response.status_code == 422, body
        assert response.json()["errors"][0]["field"] == field, body


async def test_non_admin_cannot_update(
    client: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    await add_member(db, organization.id, email="fajar@contoh.id", role="form_editor")
    await sign_in(client, "fajar@contoh.id", organization.id)

    response = await client.patch(URL, json={"name": "Diubah"})

    assert response.status_code == 403
    assert response.json()["errors"][0]["code"] == "forbidden"


async def test_requires_session_and_workspace(
    client: AsyncClient, organization: Workspace, user: User
) -> None:
    assert (await client.get(URL)).status_code == 401
    await sign_in(client, user.email, organization.id)
    del client.headers["X-Workspace-Id"]
    assert (await client.get(URL)).json()["errors"][0]["code"] == "workspace_required"


async def test_other_workspace_is_404(
    client: AsyncClient, db: AsyncSession, organization: Workspace, user: User
) -> None:
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    await sign_in(client, user.email, other.id)

    response = await client.patch(URL, json={"name": "Diambil alih"})

    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == "workspace_not_found"
