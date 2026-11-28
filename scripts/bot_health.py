"""Print the shared bot's health now (roadmap 7.4, runbook-bot.md).

    uv run python -m scripts.bot_health

Exit code 1 when there is a problem, so it can be used in a check script.
"""

import asyncio
import json
import sys

from app.db import models as _models  # noqa: F401  every table, as in the worker
from app.db.session import open_session
from app.modules.conversations import health


async def main() -> int:
    async with open_session() as db:
        snapshot = await health.check(db)
    print(json.dumps(snapshot, indent=2))
    return 1 if snapshot["problems"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
