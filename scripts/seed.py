"""Load development seed data from fixtures/.

    uv run python -m scripts.seed demo

Idempotent: rows that already exist are skipped. Only sets that exist today are listed;
see docs/09-seeding/seed-data.md for the planned ones.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.core.config import settings
from app.core.errors import AppError
from app.db.session import SessionLocal, engine
from app.modules.auth import repository, service
from app.modules.workspaces import service as workspaces_service

FIXTURES = Path(__file__).parents[1] / "fixtures"


async def seed_demo() -> None:
    """Three demo users, each with a personal workspace, sharing the organization
    "Fluctuz Indonesia" as admin, form_editor and reviewer (ROADMAP 1.7)."""
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
        await workspaces_service.seed_organization(
            db, name=org["name"], seed_key=org["seed_key"], members=members
        )
        roles = ", ".join(f"{u['email']}={u['role']}" for u in data["users"])
        print(f"workspace {org['name']}: {roles}")


SETS = {"demo": seed_demo}


async def main(name: str) -> None:
    try:
        await SETS[name]()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if not settings.is_development:
        sys.exit("Demo accounts have a published password: development only.")
    parser = argparse.ArgumentParser(description="Load seed data.")
    parser.add_argument("set", choices=SETS)
    asyncio.run(main(parser.parse_args().set))
