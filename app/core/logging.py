"""Send the app's own log records (`app.*`) to stderr.

Uvicorn configures only its own loggers, so without this `logger.info` in app code is dropped,
including the development emails that `core/mail.py` logs instead of sending.
Minimal on purpose: structured JSON logs with the request id come with ROADMAP 0.4.
"""

import logging


def configure_logging() -> None:
    logger = logging.getLogger("app")
    if logger.handlers:  # already configured (reload, tests)
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
