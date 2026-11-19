"""Background jobs (B-XXX: Taskiq on Redis streams; replaces arq, B-003).

Jobs live in each module's `jobs.py` and are registered by importing it in `app/worker.py`.
Run them with:

    taskiq worker app.worker:broker      # executes jobs
    taskiq scheduler app.worker:scheduler  # starts cron jobs (one instance only)

Redis streams with a consumer group keep a job until a worker acknowledges it, so a worker that
dies mid-job does not lose it. Failed jobs retry with exponential backoff. With QUEUE_INLINE
(tests, quick local runs) a job runs in the calling process when it is sent.
"""

from taskiq import AsyncBroker, InMemoryBroker, SmartRetryMiddleware
from taskiq_redis import RedisStreamBroker

from app.core.config import settings

DEFAULT_RETRIES = 3


def _broker() -> AsyncBroker:
    if settings.queue_inline:
        return InMemoryBroker(await_inplace=True)
    return RedisStreamBroker(
        url=settings.redis_url, queue_name="fluctuz:jobs", consumer_group_name="fluctuz"
    ).with_middlewares(
        SmartRetryMiddleware(
            default_retry_count=DEFAULT_RETRIES,
            default_delay=5,
            use_jitter=True,
            use_delay_exponent=True,
            max_delay_exponent=300,
        )
    )


broker: AsyncBroker = _broker()
