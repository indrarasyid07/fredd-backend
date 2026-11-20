"""Field data for the demo organization (ROADMAP 4.1): a published "Survei Kondisi Tanaman",
12 extension workers in 6 West Java regencies and ~150 reports over the last 14 days, so the
dashboard has something real to show before the bot is in daily use.

Called by `scripts.seed demo` after the accounts. Idempotent: the structure and workers are
found again on reruns, and reports are only made when the demo workers have none yet. The
numbers are random but reproducible (fixed seed); dates are relative to today.

Needs the `reference` set (regions) first: a report's region comes from its point.
"""

import gzip
import json
import random
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_storage
from app.core.time import now_utc
from app.modules.extension_workers import service as workers_service
from app.modules.forms import service as forms_service
from app.modules.forms.schemas import FieldDefinition, FormDefinition
from app.modules.reference_data import service as reference_service
from app.modules.reports import service as reports_service

FIXTURES = Path(__file__).parents[1] / "fixtures"
TZ = ZoneInfo("Asia/Jakarta")
# Share of reports per condition (dashboard.md example: 58 / 27 / 15).
CONDITION_WEIGHTS = {"healthy": 58, "attention": 27, "infected": 15}
# Workers that report today; the rest show as "belum lapor" on the dashboard.
ACTIVE_TODAY = 9
WORK_START, WORK_HOURS = time(6, 30), 11


def _centroids() -> dict[str, tuple[float, float]]:
    """District code → (lat, lng) from the reference fixture."""
    with gzip.open(FIXTURES / "reference" / "regions.geojson.gz", "rt", encoding="utf-8") as f:
        features = json.load(f)["features"]
    out = {}
    for feature in features:
        p = feature["properties"]
        if p.get("level") == "district":
            lng, lat = p["centroid"]
            out[p["code"]] = (lat, lng)
    return out


async def seed_field(db: AsyncSession, workspace_id: uuid.UUID, admin_user_id: uuid.UUID) -> None:
    data = json.loads((FIXTURES / "demo" / "field.json").read_text(encoding="utf-8"))
    centroids = _centroids()
    homes = [centroids[w["district"]] for w in data["workers"]]
    first = await reference_service.locate(db, lat=homes[0][0], lng=homes[0][1])
    if first.regency is None:
        print("field data skipped: run `python -m scripts.seed reference` first (regions)")
        return

    form_id, version_id, definition = await _structure(db, workspace_id, admin_user_id, data)
    photo_keys = await _photos(workspace_id, data["photos"])

    workers = []
    joined = now_utc() - timedelta(days=data["reports"]["days"] + 7)
    for item, (lat, lng) in zip(data["workers"], homes, strict=True):
        path = await reference_service.locate(db, lat=lat, lng=lng)
        region = path.district or path.regency
        workers.append(
            await workers_service.seed_demo_worker(
                db,
                workspace_id=workspace_id,
                form_id=form_id,
                name=item["name"],
                phone_e164=item["phone"],
                telegram_user_id=item["phone"][-10:] if item["channel"] == "telegram" else None,
                region_id=region.id if region else None,
                joined_at=joined,
            )
        )
    await db.commit()
    print(f"workers {len(workers)} on '{data['form']['name']}'")

    existing, _ = await reports_service.list_reports(
        db, workspace_id, extension_worker_id=workers[0].id, limit=1
    )
    if existing:
        print("reports skip (the demo workers already have reports)")
        return

    rng = random.Random(data["reports"]["random_seed"])
    made = 0
    for worker_index, received in _schedule(rng, data["reports"], len(workers)):
        worker = workers[worker_index]
        answers = _answers(rng, definition, homes[worker_index], data, photo_keys)
        reasons = _review_reasons(definition, answers)
        await reports_service.create_report(
            db,
            workspace_id=workspace_id,
            form_id=form_id,
            form_version_id=version_id,
            definition=definition,
            extension_worker_id=worker.id,
            conversation_id=None,
            answers=answers,
            needs_review=bool(reasons),
            review_reasons=reasons,
            received_at=received,
        )
        if worker.last_active_at is None or worker.last_active_at < received:
            worker.last_active_at = received
        made += 1
    await db.commit()
    print(f"reports {made} over {data['reports']['days']} days")


async def _structure(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, data: dict[str, Any]
) -> tuple[uuid.UUID, uuid.UUID, FormDefinition]:
    """The demo structure, published. An existing active structure with the same name is reused
    when it has what the dashboard reads (a location, a condition and an area field)."""
    name = data["form"]["name"]
    forms, _ = await forms_service.list_forms(db, workspace_id, before=None, limit=100)
    for form in forms:
        if form.name == name and form.status == "active" and form.current_version_id:
            version = await forms_service.get_version_definition(
                db, workspace_id, form.current_version_id
            )
            d = version.definition
            if d.field_with_role("condition") and d.field_with_role("area") and _location(d):
                print(f"form '{name}' reused (v{version.version})")
                return form.id, version.version_id, d
    definition = FormDefinition.model_validate(data["form"]["definition"])
    created = await forms_service.create_form(db, workspace_id, user_id, name, definition)
    detail = await forms_service.publish_form(db, workspace_id, user_id, created.id)
    assert detail.current_version_id is not None
    print(f"form '{name}' created and published")
    return created.id, detail.current_version_id, definition


def _location(definition: FormDefinition) -> FieldDefinition | None:
    return next((f for f in definition.fields if f.type == "location"), None)


async def _photos(workspace_id: uuid.UUID, names: list[str]) -> list[str]:
    """Sample photos stored once under the organization (overwritten on reruns)."""
    keys = []
    for name in names:
        key = f"workspaces/{workspace_id}/demo/{name}"
        data = (FIXTURES / "demo" / "photos" / name).read_bytes()
        await get_storage().put(key, data, "image/jpeg")
        keys.append(key)
    return keys


def _schedule(rng: random.Random, plan: dict[str, Any], workers: int) -> list[tuple[int, datetime]]:
    """(worker, received_at) pairs: more reports on recent days, working hours only, nothing in
    the future, and only the first ACTIVE_TODAY workers report today."""
    now = now_utc().astimezone(TZ)
    days = plan["days"]
    weights = [4 + i for i in range(days)]  # oldest → today
    out = []
    for i, weight in enumerate(weights):
        day = (now - timedelta(days=days - 1 - i)).date()
        count = round(plan["total"] * weight / sum(weights))
        start = datetime.combine(day, WORK_START, TZ)
        for _ in range(count):
            when = start + timedelta(minutes=rng.uniform(0, WORK_HOURS * 60))
            if when >= now:
                continue
            today = day == now.date()
            worker = rng.randrange(ACTIVE_TODAY if today else workers)
            out.append((worker, when.astimezone(ZoneInfo("UTC"))))
    return sorted(out, key=lambda pair: pair[1])


def _answers(
    rng: random.Random,
    definition: FormDefinition,
    home: tuple[float, float],
    data: dict[str, Any],
    photo_keys: list[str],
) -> dict[str, Any]:
    """An answer for every field, by type and role, like the chat stores them."""
    condition = rng.choices(list(CONDITION_WEIGHTS), weights=list(CONDITION_WEIGHTS.values()))[0]
    answers: dict[str, Any] = {}
    for f in definition.fields:
        if f.role == "condition":
            answers[f.key] = condition
        elif f.role == "area" or f.type == "number":
            # A couple of very large plots trip the "review above" check.
            area = rng.choice([60, 75]) if rng.random() < 0.015 else rng.uniform(0.2, 3.0)
            answers[f.key] = str(Decimal(str(round(area, 1))))
        elif f.type == "location":
            lat = home[0] + rng.uniform(-0.01, 0.01)
            lng = home[1] + rng.uniform(-0.01, 0.01)
            answers[f.key] = {"lat": round(lat, 6), "lng": round(lng, 6),
                              "accuracy_m": rng.randint(4, 25)}  # fmt: skip
        elif f.type == "short_text":
            answers[f.key] = rng.choice(data["farmers"])
        elif f.type == "long_text":
            answers[f.key] = rng.choice(data["notes"]) if rng.random() < 0.4 else None
        elif f.type == "single_choice" and f.options:
            answers[f.key] = rng.choice(f.options).value
        elif f.type == "multi_choice" and f.options:
            answers[f.key] = [f.options[0].value]
        elif f.type == "datetime":
            answers[f.key] = now_utc().astimezone(TZ).date().isoformat()
        elif f.type == "photo":
            wanted = condition == "infected" or rng.random() < 0.5
            answers[f.key] = rng.sample(photo_keys, rng.randint(1, 3)) if wanted else None
        else:
            answers[f.key] = None
    return answers


def _review_reasons(definition: FormDefinition, answers: dict[str, Any]) -> list[str]:
    """The same reasons the chat records: rules asking for review, and numbers above
    `review_above`."""
    reasons = [
        f"rule:{i}"
        for i, rule in enumerate(definition.rules)
        if rule.then.needs_review and answers.get(rule.if_.field) == rule.if_.equals
    ]
    for f in definition.fields:
        value = answers.get(f.key)
        if f.type == "number" and f.review_above is not None and value is not None:
            if Decimal(str(value)) > Decimal(str(f.review_above)):
                reasons.append(f"review_above:{f.key}")
    return reasons
