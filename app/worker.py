"""Background worker and cron entry point (Taskiq, B-XXX).

    taskiq worker app.worker:broker
    taskiq scheduler app.worker:scheduler

Every module with jobs is imported here so its tasks register on the broker. Cron jobs carry a
`schedule` label and are started by the single scheduler process.
"""

import datetime as dt

from taskiq import TaskiqEvents, TaskiqScheduler, TaskiqState
from taskiq.schedule_sources import LabelScheduleSource

import app.db.models  # noqa: F401  every table, so foreign keys resolve in jobs
from app.core import jobs as core_jobs
from app.core.logging import configure_logging
from app.core.queue import broker
from app.core.redis import redis
from app.db.session import engine
from app.modules.channels import telegram
from app.modules.conversations import jobs as conversation_jobs

HEARTBEAT_KEY = "worker:heartbeat"


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _startup(_: TaskiqState) -> None:
    configure_logging()


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _shutdown(_: TaskiqState) -> None:
    await telegram.get_client().aclose()
    await redis.aclose()
    await engine.dispose()


@broker.task(task_name="system.heartbeat", schedule=[{"cron": "* * * * *"}])
async def heartbeat_job() -> None:
    """Proves the worker and scheduler run: health checks read this key's age."""
    await redis.set(HEARTBEAT_KEY, dt.datetime.now(dt.UTC).isoformat(), ex=600)


scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])

__all__ = ["broker", "conversation_jobs", "core_jobs", "heartbeat_job", "scheduler"]
