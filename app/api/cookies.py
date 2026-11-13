from fastapi import Request, Response

from app.core.config import settings

SESSION_COOKIE = "fredd_session"


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_days * 24 * 60 * 60,
        httponly=True,
        secure=not settings.is_development,  # local dev runs over plain http
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE, httponly=True, secure=not settings.is_development, samesite="lax", path="/"
    )


def read_session_token(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE) or None
