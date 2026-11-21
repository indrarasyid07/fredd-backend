"""GET /reports and /reports/{id} (roadmap 4.3): newest first with filters and a cursor, the
detail labelled by the structure version the report was made with, signed photo links, and the
workspace boundary."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extension_workers.models import ExtensionWorker
from app.modules.forms import service as forms
from app.modules.forms.models import Form, FormVersion
from app.modules.forms.schemas import FormDefinition
from app.modules.reports import service
from app.modules.reports.models import Report
from app.modules.workspaces.models import Workspace
from tests.conftest import add_member, sign_in
from tests.form_definitions import crop_survey

URL = "/api/v1/reports"
DEFINITION = FormDefinition.model_validate(crop_survey())
NOON = datetime(2026, 11, 18, 5, 0, tzinfo=UTC)

ANSWERS: dict[str, Any] = {
    "location": {"lat": -6.82, "lng": 107.14, "accuracy_m": 8},
    "farmer_name": "Pak Slamet",
    "land_area": "1.5",
    "condition": "infected",
    "photos": ["workspaces/x/messages/2026/11/a.jpg", "telegram:AgAC-old"],
}


class Topic:
    def __init__(self, workspace: Workspace, form: Form, version: FormVersion, worker: Any):
        self.workspace, self.form, self.version, self.worker = workspace, form, version, worker

    async def report(
        self, db: AsyncSession, answers: dict[str, Any] | None = None, **kw: Any
    ) -> Report:
        return await service.create_report(
            db,
            workspace_id=self.workspace.id,
            form_id=self.form.id,
            form_version_id=self.version.id,
            definition=DEFINITION,
            extension_worker_id=self.worker.id,
            conversation_id=None,
            answers=answers if answers is not None else ANSWERS,
            **kw,
        )


async def _topic(db: AsyncSession, workspace: Workspace, worker_name: str = "Budi") -> Topic:
    form = await forms.create_form(db, workspace.id, None, "Survei Tanaman", DEFINITION)
    version = await db.scalar(select(FormVersion).where(FormVersion.form_id == form.id))
    worker = ExtensionWorker(workspace_id=workspace.id, name=worker_name, telegram_user_id="7")
    db.add(worker)
    await db.flush()
    assert version is not None
    return Topic(workspace, form, version, worker)


async def test_list_newest_first_with_names(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    older = await topic.report(db, received_at=NOON - timedelta(hours=1))
    newer = await topic.report(db, received_at=NOON)
    body = (await admin.get(URL)).json()
    assert body["success"] and body["errors"] == []
    assert [r["id"] for r in body["data"]] == [str(newer.id), str(older.id)]
    row = body["data"][0]
    assert row["code"] == newer.code and row["code"].startswith("LP-")
    assert row["form"]["name"] == "Survei Tanaman" and row["worker"]["name"] == "Budi"
    assert (row["channel"], row["condition"], row["area_ha"]) == ("telegram", "infected", 1.5)
    assert (row["photo_count"], row["complete"]) == (2, True)
    assert body["meta"]["pagination"] == {"next_cursor": None, "limit": 20, "has_more": False}


async def test_cursor_pages_through_reports(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    made = [await topic.report(db, received_at=NOON - timedelta(minutes=i)) for i in range(5)]
    first = (await admin.get(URL, params={"limit": 2})).json()
    assert first["meta"]["pagination"]["has_more"] is True
    seen = [r["id"] for r in first["data"]]
    cursor = first["meta"]["pagination"]["next_cursor"]
    while cursor:
        page = (await admin.get(URL, params={"limit": 2, "cursor": cursor})).json()
        seen += [r["id"] for r in page["data"]]
        cursor = page["meta"]["pagination"]["next_cursor"]
    assert seen == [str(r.id) for r in made]
    bad = await admin.get(URL, params={"cursor": "rusak!!"})
    assert bad.status_code == 400 and bad.json()["errors"][0]["code"] == "invalid_cursor"


async def test_filters(admin: AsyncClient, db: AsyncSession, topic: Topic) -> None:
    sick = await topic.report(db, received_at=NOON, needs_review=True, review_reasons=["rule:0"])
    healthy = await topic.report(db, {**ANSWERS, "condition": "healthy"}, received_at=NOON)
    unknown = await topic.report(db, {**ANSWERS, "condition": None}, received_at=NOON)
    old = await topic.report(db, received_at=NOON - timedelta(days=3))

    async def ids(**params: Any) -> set[str]:
        return {r["id"] for r in (await admin.get(URL, params=params)).json()["data"]}

    assert await ids(condition="healthy") == {str(healthy.id)}
    assert await ids(condition=["unknown", "healthy"]) == {str(unknown.id), str(healthy.id)}
    assert await ids(needs_review="true") == {str(sick.id)}
    since = (NOON - timedelta(days=1)).isoformat()
    assert str(old.id) not in await ids(since=since)
    assert await ids(until=since) == {str(old.id)}
    assert len(await ids(extension_worker_id=str(topic.worker.id))) == 4
    assert await ids(form_id=str(uuid.uuid4())) == set()


async def test_detail_reads_every_answer(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    report = await topic.report(
        db, received_at=NOON, needs_review=True, review_reasons=["rule:0", "review_above:land_area"]
    )
    body = (await admin.get(f"{URL}/{report.id}")).json()
    data = body["data"]
    assert data["code"] == report.code and data["form"]["version"] == topic.version.version
    assert data["location"] == {"lat": -6.82, "lng": 107.14, "accuracy_m": 8.0}
    shown = {f["key"]: f["display"] for f in data["fields"]}
    assert [f["key"] for f in data["fields"]] == [f.key for f in DEFINITION.fields]
    assert shown == {
        "location": "-6.82000, 107.14000 (akurasi 8 m)",
        "farmer_name": "Pak Slamet",
        "land_area": "1,5 ha",
        "condition": "Terserang",
        "photos": "2 foto",
    }
    assert data["review"] == {
        "needs_review": True,
        "reasons": ["Aturan: Kondisi tanaman = Terserang", "Luas lahan di atas 50 ha"],
    }


async def test_skipped_answer_reads_as_skipped(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    report = await topic.report(db, {**ANSWERS, "photos": None})
    fields = (await admin.get(f"{URL}/{report.id}")).json()["data"]["fields"]
    assert next(f for f in fields if f["key"] == "photos")["display"] == "Dilewati"


async def test_photos_get_signed_links_only_when_stored(
    admin: AsyncClient, db: AsyncSession, topic: Topic, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Signing:
        async def signed_url(self, key: str, seconds: int) -> str:
            return f"https://files.example/{key}?ttl={seconds}"

    monkeypatch.setattr("app.core.storage.override", Signing())
    report = await topic.report(db)
    photos = (await admin.get(f"{URL}/{report.id}")).json()["data"]["photos"]
    assert [(p["field_key"], p["position"]) for p in photos] == [("photos", 0), ("photos", 1)]
    assert photos[0]["url"].startswith("https://files.example/workspaces/x/messages/")
    assert photos[0]["expires_at"] is not None
    # Still a Telegram reference (its copy failed): no link rather than a broken one.
    assert (photos[1]["url"], photos[1]["expires_at"]) == (None, None)


async def test_old_report_keeps_its_version_labels(
    admin: AsyncClient, db: AsyncSession, topic: Topic
) -> None:
    report = await topic.report(db)
    renamed = crop_survey()
    renamed["fields"][1]["label"] = "Nama pemilik lahan"
    newer = FormVersion(
        workspace_id=topic.workspace.id,
        form_id=topic.form.id,
        version=topic.version.version + 1,
        definition=renamed,
        published_at=NOON,
    )
    db.add(newer)
    await db.flush()
    topic.form.current_version_id = newer.id
    await db.flush()
    fields = (await admin.get(f"{URL}/{report.id}")).json()["data"]["fields"]
    assert fields[1]["label"] == "Nama petani"


async def test_other_workspace_reports_are_not_found(
    client: AsyncClient, db: AsyncSession, organization: Workspace, topic: Topic
) -> None:
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    await add_member(db, other.id, email="rani@contoh.id", role="reviewer")
    report = await topic.report(db)
    await sign_in(client, "rani@contoh.id", other.id)
    assert (await client.get(URL)).json()["data"] == []
    missing = await client.get(f"{URL}/{report.id}")
    assert missing.status_code == 404
    assert missing.json()["errors"][0]["code"] == "report_not_found"


async def test_reviewer_may_read_and_strangers_may_not(
    client: AsyncClient, db: AsyncSession, organization: Workspace, topic: Topic
) -> None:
    report = await topic.report(db)
    assert (await client.get(URL)).status_code == 401
    await add_member(db, organization.id, email="rani@contoh.id", role="reviewer")
    await sign_in(client, "rani@contoh.id", organization.id)
    assert (await client.get(f"{URL}/{report.id}")).status_code == 200
    # Someone outside the organization cannot pick it as their workspace.
    other = Workspace(name="Dinas Lain", type="organization")
    db.add(other)
    await db.flush()
    await add_member(db, other.id, email="x@contoh.id", role="admin")
    await sign_in(client, "x@contoh.id", organization.id)
    assert (await client.get(URL)).status_code in (403, 404)


# --- Voice Lab (roadmap 12.4) -------------------------------------------------------------------

VOICE = {
    "transcript": "nama petani Pak Slamet, luas 1,5 hektar",
    "audio": "workspaces/x/messages/2026/11/voice.ogg",
    "heard": {"farmer_name": "Pak Slamet", "land_area": "1,5 hektar"},
    "confidence": {"farmer_name": 0.75, "land_area": 0.5},
}


async def test_voice_reports_list_and_detail(
    admin: AsyncClient, db: AsyncSession, topic: Topic, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Signing:
        async def signed_url(self, key: str, seconds: int) -> str:
            return f"https://files.example/{key}"

    monkeypatch.setattr("app.core.storage.override", Signing())
    chat = await topic.report(db, received_at=NOON)
    spoken = await topic.report(db, received_at=NOON - timedelta(minutes=5), voice=VOICE)

    rows = (await admin.get(URL, params={"voice": "true"})).json()["data"]
    assert [r["id"] for r in rows] == [str(spoken.id)]
    assert rows[0]["transcript"] == VOICE["transcript"]
    others = (await admin.get(URL, params={"voice": "false"})).json()["data"]
    assert [r["id"] for r in others] == [str(chat.id)]

    voice = (await admin.get(f"{URL}/{spoken.id}")).json()["data"]["voice"]
    assert voice["transcript"] == VOICE["transcript"]
    assert voice["audio_url"] == "https://files.example/workspaces/x/messages/2026/11/voice.ogg"
    assert voice["audio_expires_at"] is not None
    # Version order; doubtful values flagged.
    assert [(f["label"], f["heard"], f["confident"]) for f in voice["fields"]] == [
        ("Nama petani", "Pak Slamet", True),
        ("Luas lahan", "1,5 hektar", False),
    ]
    assert (await admin.get(f"{URL}/{chat.id}")).json()["data"]["voice"] is None
