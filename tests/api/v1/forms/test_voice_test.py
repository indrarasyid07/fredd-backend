"""Voice fields and "Uji dengan ucapan" (roadmap 12.2): spoken names and unit words per field, a
voice input mode per structure, and POST /forms/{id}/voice-test reading a sentence with the
draft being edited."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.workspaces.models import Workspace
from tests.conftest import add_member, sign_in

URL = "/api/v1/forms"


def lab(**changes: Any) -> dict[str, Any]:
    fields: list[dict[str, Any]] = [
        {"key": "sample", "type": "short_text", "label": "Nomor sampel", "question": "Sampel?",
         "voice_cues": ["sampel", "kode sampel"]},
        {"key": "ph", "type": "number", "label": "pH", "question": "pH?"},
        {"key": "temp", "type": "number", "label": "Suhu", "question": "Suhu?", "unit": "°C",
         "unit_aliases": ["derajat celsius", "dercel"]},
        {"key": "volume", "type": "number", "label": "Volume", "question": "Volume?",
         "unit": "mL", "required": False},
    ]  # fmt: skip
    for f in fields:
        f.update(changes.get(f["key"], {}))
    return {"fields": fields, "rules": []}


@pytest.fixture
async def editor(client: AsyncClient, db: AsyncSession, organization: Workspace) -> AsyncClient:
    await add_member(db, organization.id, email="fajar@contoh.id", role="form_editor")
    return await sign_in(client, "fajar@contoh.id", organization.id)


async def _draft(editor: AsyncClient, definition: dict[str, Any], **extra: Any) -> str:
    response = await editor.post(URL, json={"name": "Uji Air", "definition": definition, **extra})
    assert response.status_code == 200, response.json()
    return response.json()["data"]["id"]


async def test_a_sentence_is_read_with_the_draft(editor: AsyncClient) -> None:
    form_id = await _draft(editor, lab())
    said = "Kode sampel S-2041, pH 6,8, suhu 25 dercel"
    response = await editor.post(f"{URL}/{form_id}/voice-test", json={"text": said})
    assert response.status_code == 200
    data = response.json()["data"]
    got = {v["key"]: (v["value"], v["display"], v["confident"]) for v in data["values"]}
    assert got == {
        "sample": ("S-2041", "S-2041", True),
        "ph": ("6.8", "6,8", True),
        "temp": ("25", "25 °C", True),  # "dercel" is this field's unit word
    }
    assert data["missing"] == []  # volume is optional
    assert next(v for v in data["values"] if v["key"] == "temp")["heard"] == "25 dercel"


async def test_doubts_and_missing_fields_are_shown(editor: AsyncClient) -> None:
    form_id = await _draft(editor, lab())
    response = await editor.post(f"{URL}/{form_id}/voice-test", json={"text": "suhu 25 ml"})
    data = response.json()["data"]
    (temp,) = data["values"]
    assert (temp["label"], temp["confident"]) == ("Suhu", False)
    assert temp["doubt"] == "Satuan yang terdengar bukan °C"
    assert [m["label"] for m in data["missing"]] == ["Nomor sampel", "pH"]


async def test_edits_to_the_draft_apply_at_once(editor: AsyncClient) -> None:
    form_id = await _draft(editor, lab())
    before = await editor.post(f"{URL}/{form_id}/voice-test", json={"text": "kadar 7"})
    assert before.json()["data"]["values"] == []
    patched = await editor.patch(
        f"{URL}/{form_id}", json={"definition": lab(ph={"voice_cues": ["kadar"]})}
    )
    assert patched.status_code == 200
    after = await editor.post(f"{URL}/{form_id}/voice-test", json={"text": "kadar 7"})
    assert [v["key"] for v in after.json()["data"]["values"]] == ["ph"]


async def test_voice_input_mode_is_kept(editor: AsyncClient) -> None:
    form_id = await _draft(editor, lab(), settings={"input_mode": "voice"})
    detail = (await editor.get(f"{URL}/{form_id}")).json()["data"]
    assert detail["settings"]["input_mode"] == "voice"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"sample": {"unit_aliases": ["buah"]}}, "unit_aliases_not_allowed"),
        ({"sample": {"type": "photo", "voice_cues": ["foto"]}}, "voice_cues_not_allowed"),
    ],
)
async def test_voice_words_only_where_they_apply(
    editor: AsyncClient, changes: dict[str, Any], code: str
) -> None:
    form_id = await _draft(editor, lab(**changes))
    checked = (await editor.post(f"{URL}/{form_id}/validate")).json()["data"]
    assert code in [e["code"] for e in checked["errors"]]


async def test_reviewers_and_other_workspaces_cannot_test(
    client: AsyncClient, db: AsyncSession, organization: Workspace, editor: AsyncClient
) -> None:
    form_id = await _draft(editor, lab())
    await add_member(db, organization.id, email="rani@contoh.id", role="reviewer")
    await sign_in(client, "rani@contoh.id", organization.id)
    body = {"text": "pH 7"}
    assert (await client.post(f"{URL}/{form_id}/voice-test", json=body)).status_code == 403

    other = Workspace(name="Lab Lain", type="organization")
    db.add(other)
    await db.flush()
    await add_member(db, other.id, email="x@contoh.id", role="admin")
    await sign_in(client, "x@contoh.id", other.id)
    assert (await client.post(f"{URL}/{form_id}/voice-test", json=body)).status_code == 404
    empty = await client.post(f"{URL}/{form_id}/voice-test", json={"text": ""})
    assert empty.status_code == 422
