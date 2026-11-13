from fastapi import APIRouter, Request, Response

from app.api.cookies import clear_session_cookie, read_session_token, set_session_cookie
from app.api.deps import DB, CurrentUser, client_ip
from app.api.responses import ApiErrorResponse, ApiResponse, ok
from app.modules.auth import service
from app.modules.auth.schemas import LoginRequest, MeResponse

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
