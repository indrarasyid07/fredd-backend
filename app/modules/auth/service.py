"""Auth business logic. Knows nothing about HTTP: callers pass in ip/user agent and set cookies."""

import asyncio
import re
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.config import settings
from app.core.security import (
    hash_password,
    hash_token,
    new_token,
    password_needs_rehash,
    verify_password,
)
from app.core.time import now_utc
from app.modules.auth import errors, repository
from app.modules.auth.models import User
from app.modules.auth.schemas import MeResponse, UserOut

LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_LIMIT_PER_EMAIL = 5  # failures per ip + email
LOGIN_LIMIT_PER_IP = 30  # failures per ip across emails
TOUCH_INTERVAL = timedelta(minutes=5)  # how stale last_seen_at may get before we write it


def _rate_keys(ip: str | None, email: str) -> tuple[str, str]:
    return f"rl:login:{ip}:{email}", f"rl:login:{ip}"


async def login(
    db: AsyncSession, email: str, password: str, *, ip: str | None, user_agent: str | None
) -> tuple[str, MeResponse]:
    """Return a new session token and the user's profile. `email` must already be normalized."""
    email_key, ip_key = _rate_keys(ip, email)
    for key, limit in ((email_key, LOGIN_LIMIT_PER_EMAIL), (ip_key, LOGIN_LIMIT_PER_IP)):
        if (wait := await rate_limit.retry_after(key, limit)) is not None:
            raise errors.TooManyAttempts(wait)

    user = await repository.get_user_by_email(db, email)
    password_hash = user.password_hash if user else None
    if user is None or not await asyncio.to_thread(verify_password, password, password_hash):
        await rate_limit.hit(email_key, LOGIN_WINDOW_SECONDS)
        await rate_limit.hit(ip_key, LOGIN_WINDOW_SECONDS)
        raise errors.InvalidCredentials()

    assert password_hash is not None  # verify_password is False for Google-only accounts
    if password_needs_rehash(password_hash):
        new_hash = await asyncio.to_thread(hash_password, password)
        await repository.update_password_hash(db, user, new_hash)

    token = new_token()
    now = now_utc()
    await repository.create_session(
        db,
        user_id=user.id,
        token_hash=hash_token(token),
        ip=ip,
        user_agent=(user_agent or "")[:500] or None,
        now=now,
        expires_at=now + timedelta(days=settings.session_ttl_days),
    )
    await db.commit()
    await rate_limit.reset(email_key)
    return token, await get_me(db, user)


async def logout(db: AsyncSession, token: str) -> None:
    await repository.revoke_session_by_token(db, hash_token(token), now_utc())
    await db.commit()


async def resolve_session(db: AsyncSession, token: str) -> User:
    """Return the user behind a session token and slide its expiry.

    Raises NotAuthenticated when the token is unknown, revoked or expired.
    """
    now = now_utc()
    session = await repository.get_active_session(db, hash_token(token), now)
    if session is None:
        raise errors.NotAuthenticated()
    user = await repository.get_user(db, session.user_id)
    if user is None:
        raise errors.NotAuthenticated()
    if now - session.last_seen_at > TOUCH_INTERVAL:
        await repository.touch_session(
            db, session, now=now, expires_at=now + timedelta(days=settings.session_ttl_days)
        )
        await db.commit()
    return user


async def get_me(db: AsyncSession, user: User) -> MeResponse:
    # Memberships arrive with the workspaces module.
    return MeResponse(user=UserOut.model_validate(user), memberships=[])


_STRONG_PASSWORD = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,128}$")


async def create_user(db: AsyncSession, *, email: str, name: str, password: str) -> User:
    """Create a password user (used by scripts/create_user.py now, registration later)."""
    email = email.strip().lower()
    if not _STRONG_PASSWORD.match(password):
        raise errors.WeakPassword(field="password")
    if await repository.get_user_by_email(db, email):
        raise errors.EmailAlreadyRegistered(field="email")
    password_hash = await asyncio.to_thread(hash_password, password)
    user = await repository.create_user(
        db, email=email, name=name.strip(), password_hash=password_hash
    )
    await db.commit()
    return user
