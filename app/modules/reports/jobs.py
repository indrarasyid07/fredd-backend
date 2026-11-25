"""Report jobs (Taskiq). Thin: open a session, call the module."""

import uuid

from app.core.queue import broker
from app.db import session as db_session
from app.modules.reports import photo_checks


@broker.task(task_name="reports.check_photos")
async def check_photos_job(workspace_id: str, report_id: str) -> None:
    """AI notes on a new report's photos (roadmap 12.7). Not retried: a note is advice, and a
    second attempt would only repeat the same call."""
    async with db_session.open_session() as db:
        await photo_checks.check_report_photos(db, uuid.UUID(workspace_id), uuid.UUID(report_id))
