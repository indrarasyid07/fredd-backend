"""Platform jobs that belong to no feature module."""

from app.core import mail
from app.core.queue import broker


@broker.task(task_name="email.send", retry_on_error=True)
async def send_email_job(to: str, subject: str, body: str, html: str | None = None) -> None:
    # Looked up at call time so the `outbox` test fixture still captures it.
    await mail.send_email(to, subject, body, html)
