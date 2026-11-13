from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.responses import ErrorItem, error_response
from app.core.config import settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MESSAGE = "Permintaan ditolak karena berasal dari situs lain."


def _origin(request: Request) -> str:
    origin = request.headers.get("origin")
    if not origin:  # some browsers omit Origin; fall back to Referer
        referer = urlsplit(request.headers.get("referer", ""))
        origin = f"{referer.scheme}://{referer.netloc}" if referer.netloc else ""
    return origin.rstrip("/")


class CsrfMiddleware:
    """Reject state-changing /api requests whose Origin is not the Fredd web app.

    Works with the SameSite=Lax session cookie; webhooks are outside /api and use signatures.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/api/"):
            request = Request(scope)
            if (
                request.method not in SAFE_METHODS
                and _origin(request) not in settings.trusted_origins
            ):
                item = ErrorItem(code="csrf_rejected", message=MESSAGE)
                await error_response(403, [item], MESSAGE)(scope, receive, send)
                return
        await self.app(scope, receive, send)
