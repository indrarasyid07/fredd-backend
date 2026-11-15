from fastapi import Request, Response

from app.core.config import settings

SESSION_COOKIE = "fredd_session"
OAUTH_COOKIE = "fredd_oauth"  # Google sign-in state, 10 minutes
OAUTH_PATH = "/api/v1/auth/google"


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


def set_oauth_cookie(response: Response, state: str) -> None:
    response.set_cookie(
        OAUTH_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=not settings.is_development,
        samesite="lax",  # must come back on Google's top-level redirect
        path=OAUTH_PATH,
    )


def clear_oauth_cookie(response: Response) -> None:
    response.delete_cookie(OAUTH_COOKIE, httponly=True, samesite="lax", path=OAUTH_PATH)


def read_oauth_state(request: Request) -> str | None:
    return request.cookies.get(OAUTH_COOKIE) or None
