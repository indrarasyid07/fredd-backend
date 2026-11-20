"""/devtools chat simulator: the real pipeline from a browser, development only (roadmap 3.9)."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.main import create_app
from app.modules.conversations.engine import copy
from app.modules.forms import service as forms
from app.modules.forms.models import Form
from app.modules.forms.schemas import FormDefinition
from app.modules.join_codes import repository as join_codes
from app.modules.workspaces.models import Workspace
from tests.form_definitions import crop_survey

URL = "/devtools/telegram/messages"


async def test_page_is_served(client: AsyncClient) -> None:
    response = await client.get("/devtools")
    assert response.status_code == 200
    assert "Simulator chat bot" in response.text


async def test_stranger_gets_join_instructions(client: AsyncClient) -> None:
    response = await client.post(URL, json={"text": "halo"})
    assert response.status_code == 200
    assert response.json()["replies"] == [
        {"direction": "out", "text": copy.JOIN_FIRST, "buttons": [], "workspace_id": None,
         "at": response.json()["replies"][0]["at"]}
    ]  # fmt: skip


async def test_join_and_confirm_through_the_simulator(
    client: AsyncClient, db: AsyncSession, organization: Workspace
) -> None:
    form = await forms.create_form(
        db, organization.id, None, "Survei", FormDefinition.model_validate(crop_survey())
    )
    (await db.get(Form, form.id)).status = "active"  # type: ignore[union-attr]
    code = await join_codes.get_live_for_form(db, organization.id, form.id)
    assert code is not None
    await db.flush()

    (joined,) = (await client.post(URL, json={"text": f"/start {code.code}"})).json()["replies"]
    assert joined["workspace_id"] == str(organization.id)
    assert [b["value"] for b in joined["buttons"]] == ["join:keep", "join:change"]
    (kept,) = (await client.post(URL, json={"button": "join:keep"})).json()["replies"]
    assert kept["text"] == copy.AFTER_KEEP

    history = (await client.get("/devtools/telegram/devtools-1/messages")).json()["messages"]
    assert [m["direction"] for m in history] == ["in", "out", "in", "out"]


async def test_only_devtools_chat_ids(client: AsyncClient) -> None:
    response = await client.post(URL, json={"chat_id": "700100200", "text": "halo"})
    assert response.status_code == 422  # never a real Telegram user's chat


@pytest.mark.parametrize("environment", ["staging", "production"])
async def test_absent_outside_development(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setattr(settings, "environment", environment)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/devtools")).status_code == 404
        assert (await c.post(URL, json={"text": "halo"})).status_code == 404


async def test_location_and_photo_are_sent_as_telegram_would(client: AsyncClient) -> None:
    """The report flow (3.7) needs them; they go through the same pipeline as text."""
    for body in ({"location": {"lat": -6.82, "lng": 107.14}}, {"photo": True}):
        response = await client.post(URL, json={"chat_id": "devtools-media", **body})
        assert response.status_code == 200
    history = (await client.get("/devtools/telegram/devtools-media/messages")).json()["messages"]
    inbound = [m["text"] for m in history if m["direction"] == "in"]
    assert inbound == ["📍 -6.82, 107.14", "📷 (foto)"]
