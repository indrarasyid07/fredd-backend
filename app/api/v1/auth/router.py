from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import RedirectResponse
from redis.exceptions import RedisError

from app.api.cookies import (
    clear_oauth_cookie,
    clear_session_cookie,
    read_oauth_state,
    read_session_token,
    set_oauth_cookie,
    set_session_cookie,
)
from app.api.deps import DB, CurrentUser, client_ip
from app.api.responses import ApiErrorResponse, ApiResponse, ok
from app.core.config import settings
from app.modules.auth import google, service
from app.modules.auth.errors import GoogleError
from app.modules.auth.schemas import (
    EmailRequest,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    ResetPasswordRequest,
    TokenRequest,
)

router = APIRouter()

_ERR = {"model": ApiErrorResponse}


@router.post(
    "/login",
    response_model=ApiResponse[MeResponse],
    responses={401: _ERR, 403: _ERR, 422: _ERR, 429: _ERR},
)
async def login(body: LoginRequest, request: Request, response: Response, db: DB):
    token, me = await service.login(
        db,
        body.email,
        body.password,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    set_session_cookie(response, token)
    return ok(me, message="Berhasil masuk.")


@router.post("/logout", response_model=ApiResponse[None], responses={403: _ERR})
async def logout(request: Request, response: Response, db: DB):
    # Always succeeds, so a stale tab can still sign out cleanly.
    if (token := read_session_token(request)) is not None:
        await service.logout(db, token)
    clear_session_cookie(response)
    return ok(None, message="Berhasil keluar.")


@router.get("/me", response_model=ApiResponse[MeResponse], responses={401: _ERR})
async def get_me(user: CurrentUser, db: DB):
    return ok(await service.get_me(db, user))


@router.post(
    "/register",
    response_model=ApiResponse[None],
    responses={403: _ERR, 422: _ERR, 429: _ERR},
)
async def register(body: RegisterRequest, request: Request, db: DB, background: BackgroundTasks):
    await service.register(db, body, background, ip=client_ip(request))
    return ok(None, message="Jika email valid, kami sudah mengirim tautan verifikasi.")


@router.post(
    "/verify-email",
    response_model=ApiResponse[MeResponse],
    responses={400: _ERR, 403: _ERR, 422: _ERR, 429: _ERR},
)
async def verify_email(body: TokenRequest, request: Request, response: Response, db: DB):
    token, me = await service.verify_email(
        db,
        body.token,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    set_session_cookie(response, token)
    return ok(me, message="Email terverifikasi.")


@router.post(
    "/verify-email/resend",
    response_model=ApiResponse[None],
    responses={403: _ERR, 422: _ERR, 429: _ERR},
)
async def resend_verification(
    body: EmailRequest, request: Request, db: DB, background: BackgroundTasks
):
    await service.resend_verification(db, body, background, ip=client_ip(request))
    return ok(None, message="Jika email terdaftar, tautan verifikasi baru sudah dikirim.")


@router.post(
    "/password/forgot",
    response_model=ApiResponse[None],
    responses={403: _ERR, 422: _ERR, 429: _ERR},
)
async def forgot_password(
    body: EmailRequest, request: Request, db: DB, background: BackgroundTasks
):
    await service.forgot_password(db, body, background, ip=client_ip(request))
    return ok(None, message="Jika email terdaftar, tautan atur ulang kata sandi sudah dikirim.")


@router.post(
    "/password/reset",
    response_model=ApiResponse[None],
    responses={400: _ERR, 403: _ERR, 422: _ERR, 429: _ERR},
)
async def reset_password(body: ResetPasswordRequest, request: Request, db: DB):
    await service.reset_password(db, body, ip=client_ip(request))
    return ok(None, message="Kata sandi berhasil diubah. Silakan masuk.")


def _login_error(reason: str) -> RedirectResponse:
    response = RedirectResponse(f"{settings.app_base_url.rstrip('/')}/login?error={reason}", 303)
    clear_oauth_cookie(response)
    return response


# The two Google endpoints are opened by the browser itself, so they redirect instead of
# returning the JSON envelope, and they stay out of the OpenAPI contract.
@router.get("/google/login", include_in_schema=False)
async def google_login(next: str | None = None):
    try:
        url, state = await google.start(next)
    except GoogleError as exc:
        return _login_error(exc.reason)
    except RedisError:
        return _login_error("google_failed")
    response = RedirectResponse(url, 303)
    set_oauth_cookie(response, state)
    return response


@router.get("/google/callback", include_in_schema=False)
async def google_callback(
    request: Request,
    db: DB,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    try:
        if error:
            raise GoogleError("google_failed")
        profile, next_path = await google.finish(code, state, read_oauth_state(request))
        token = await service.login_with_google(
            db, profile, ip=client_ip(request), user_agent=request.headers.get("user-agent")
        )
    except GoogleError as exc:
        return _login_error(exc.reason)
    except RedisError:
        return _login_error("google_failed")
    response = RedirectResponse(f"{settings.app_base_url.rstrip('/')}{next_path}", 303)
    clear_oauth_cookie(response)
    set_session_cookie(response, token)
    return response
