"""Load development seed data from fixtures/.

    uv run python -m scripts.seed demo        # demo accounts + field data (development only)
    uv run python -m scripts.seed reference   # regions, commodities, units (every environment)
    uv run python -m scripts.seed templates   # wizard template catalogue (every environment)

Idempotent: rows that already exist are skipped (demo) or updated (reference). Only sets
that exist today are listed; see docs/09-seeding/seed-data.md for the planned ones.
"""

import argparse
import asyncio
import gzip
import json
import sys
from pathlib import Path

from app.core.config import settings
from app.core.errors import AppError
from app.db import models as _models  # noqa: F401  # every table, for cross-module foreign keys
from app.db.session import SessionLocal, engine
from app.modules.auth import repository, service
from app.modules.forms import service as forms_service
from app.modules.reference_data import service as reference_service
from app.modules.workspaces import service as workspaces_service
from scripts import demo_field

FIXTURES = Path(__file__).parents[1] / "fixtures"


async def seed_demo() -> None:
    """Three demo users, each with a personal workspace, sharing the organization
    "Fluctuz Indonesia" as admin, form_editor and reviewer (ROADMAP 1.7); then its field data:
    a published structure, 12 workers and ~150 reports (ROADMAP 4.1, `scripts/demo_field.py`)."""
    data = json.loads((FIXTURES / "demo" / "users.json").read_text(encoding="utf-8"))
    async with SessionLocal() as db:
        members = []
        for item in data["users"]:
            user = await repository.get_user_by_email(db, item["email"])
            if user is not None:
                print(f"skip    {item['email']}")
            else:
                try:
                    user = await service.create_user(
                        db, email=item["email"], name=item["name"], password=data["password"]
                    )
                except AppError as exc:
                    sys.exit(f"Failed for {item['email']}: {exc.message}")
                print(f"created {item['email']}")
            members.append((user.id, item["role"]))

        org = data["workspace"]
        workspace = await workspaces_service.seed_organization(
            db, name=org["name"], seed_key=org["seed_key"], members=members
        )
        roles = ", ".join(f"{u['email']}={u['role']}" for u in data["users"])
        print(f"workspace {org['name']}: {roles}")
        admin_id = next(user_id for user_id, role in members if role == "admin")
        await demo_field.seed_field(db, workspace.id, admin_id)


async def seed_reference() -> None:
    """Platform reference data: Kemendagri regions with boundaries (provinces, regencies,
    districts), standard commodities and units with their local names (ROADMAP 2.1)."""
    folder = FIXTURES / "reference"
    with gzip.open(folder / "regions.geojson.gz", "rt", encoding="utf-8") as file:
        features = json.load(file)["features"]
    lists = json.loads((folder / "commodities.json").read_text(encoding="utf-8"))
    async with SessionLocal() as db:
        regions = await reference_service.seed_platform_regions(db, features)
        commodities = await reference_service.seed_platform_items(
            db, "commodity", lists["commodities"]
        )
        units = await reference_service.seed_platform_items(db, "unit", lists["units"])
    print(f"regions {regions}, commodities {commodities}, units {units}")


async def seed_templates() -> None:
    """The wizard's template catalogue: 8 sectors, 25 templates (ROADMAP 2.3)."""
    data = json.loads((FIXTURES / "templates" / "form_templates.json").read_text(encoding="utf-8"))
    async with SessionLocal() as db:
        count = await forms_service.seed_template_catalogue(db, data["sectors"])
    print(f"sectors {len(data['sectors'])}, templates {count}")


SETS = {"demo": seed_demo, "reference": seed_reference, "templates": seed_templates}
# Sets with published credentials, refused outside development.
DEV_ONLY = {"demo"}


async def main(name: str) -> None:
    try:
        await SETS[name]()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load seed data.")
    parser.add_argument("set", choices=SETS)
    chosen = parser.parse_args().set
    if chosen in DEV_ONLY and not settings.is_development:
        sys.exit("Demo accounts have a published password: development only.")
    asyncio.run(main(chosen))
