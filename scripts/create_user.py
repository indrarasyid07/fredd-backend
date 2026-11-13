"""Create a password user for development until registration exists.

    uv run python -m scripts.create_user --email dina@contoh.id --name "Dina Admin"

The password is prompted, never passed as an argument, so it stays out of shell history.
"""

import argparse
import asyncio
import getpass
import sys

from app.core.config import settings
from app.core.errors import AppError
from app.db.session import SessionLocal, engine
from app.modules.auth import service


async def main(email: str, name: str, password: str) -> None:
    try:
        async with SessionLocal() as db:
            user = await service.create_user(db, email=email, name=name, password=password)
        print(f"Created {user.email} ({user.id})")
    except AppError as exc:
        sys.exit(f"Failed: {exc.message}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if settings.environment == "production":
        sys.exit("Refusing to run in production.")
    parser = argparse.ArgumentParser(description="Create a password user for development.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    asyncio.run(main(args.email, args.name, password))
