"""Auth business logic. Knows nothing about HTTP: callers pass in ip/user agent and set cookies."""

import asyncio
import re
from datetime import timedelta

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import mail, rate_limit
from app.core.config import settings
from app.core.security import (
    hash_password,
    hash_token,
    new_token,
    password_needs_rehash,
    verify_password,
)
from app.core.time import now_utc
from app.modules.auth import emails, errors, repository
from app.modules.auth.google import GoogleProfile
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    EmailRequest,
    MeResponse,
    RegisterRequest,
    ResetPasswordRequest,
    UserOut,
)
from app.modules.workspaces import service as workspaces_service

LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_LIMIT_PER_EMAIL = 5  # failures per ip + email
LOGIN_LIMIT_PER_IP = 30  # failures per ip across emails
TOUCH_INTERVAL = timedelta(minutes=5)  # how stale last_seen_at may get before we write it
VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(minutes=30)
HOUR = 60 * 60


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
    if user.email_verified_at is None:
        raise errors.EmailNotVerified()
    if password_needs_rehash(password_hash):
        new_hash = await asyncio.to_thread(hash_password, password)
        await repository.update_password_hash(db, user, new_hash)

    # Also covers users verified before the workspaces module existed.
    await _ensure_workspace(db, user)
    token = await _start_session(db, user, ip=ip, user_agent=user_agent)
    await db.commit()
    await rate_limit.reset(email_key)
    return token, await get_me(db, user)


async def _start_session(
    db: AsyncSession, user: User, *, ip: str | None, user_agent: str | None
) -> str:
    """Create a session row (the caller commits) and return the cookie token."""
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
    return token


async def _ensure_workspace(db: AsyncSession, user: User) -> None:
    """Every verified user owns a personal workspace (ROADMAP 1.2); the caller commits."""
    await workspaces_service.ensure_personal_workspace(db, user_id=user.id, user_name=user.name)


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
    memberships = await workspaces_service.list_memberships(db, user.id)
    return MeResponse(user=UserOut.model_validate(user), memberships=memberships)


_STRONG_PASSWORD = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,128}$")


async def create_user(db: AsyncSession, *, email: str, name: str, password: str) -> User:
    """Create an already verified password user (scripts/create_user.py and tests)."""
    email = email.strip().lower()
    if not _STRONG_PASSWORD.match(password):
        raise errors.WeakPassword(field="password")
    if await repository.get_user_by_email(db, email):
        raise errors.EmailAlreadyRegistered(field="email")
    password_hash = await asyncio.to_thread(hash_password, password)
    user = await repository.create_user(
        db, email=email, name=name.strip(), password_hash=password_hash, email_verified_at=now_utc()
    )
    await _ensure_workspace(db, user)
    await db.commit()
    return user


async def _throttle(key: str, limit: int, window: int) -> None:
    """Count one request against `key`; refuse with 429 once `limit` is used up."""
    if (wait := await rate_limit.retry_after(key, limit)) is not None:
        raise errors.TooManyAttempts(wait)
    await rate_limit.hit(key, window)


async def _issue_token(db: AsyncSession, user: User, purpose: str, ttl: timedelta) -> str:
    token, now = new_token(), now_utc()
    await repository.issue_auth_token(
        db,
        user_id=user.id,
        purpose=purpose,
        token_hash=hash_token(token),
        now=now,
        expires_at=now + ttl,
    )
    return token


def _check_password(password: str) -> None:
    if not _STRONG_PASSWORD.match(password):
        raise errors.WeakPassword(field="password")


async def register(
    db: AsyncSession, data: RegisterRequest, background: BackgroundTasks, *, ip: str | None
) -> None:
    """Sign up with email + password. Always looks the same to the caller, whether or not the
    email already has an account (the owner gets a notice instead), so it cannot be probed."""
    await _throttle(f"rl:register:{ip}", 10, HOUR)
    _check_password(data.password)
    if not data.accept_terms:
        raise errors.TermsNotAccepted(field="accept_terms")
    password_hash = await asyncio.to_thread(hash_password, data.password)  # same cost on every path

    user = await repository.get_user_by_email(db, data.email)
    if user is None:
        user = await repository.create_user(
            db,
            email=data.email,
            name=f"{data.first_name.strip()} {data.last_name.strip()}",
            password_hash=password_hash,
            organization=(data.organization or "").strip() or None,
        )
    if user.email_verified_at is None:  # new, or signed up before and never verified
        token = await _issue_token(db, user, "verify_email", VERIFY_TTL)
        await db.commit()
        background.add_task(mail.send_email, user.email, *emails.verify_email(token))
    else:
        background.add_task(mail.send_email, user.email, *emails.already_registered())


async def resend_verification(
    db: AsyncSession, data: EmailRequest, background: BackgroundTasks, *, ip: str | None
) -> None:
    await _throttle(f"rl:resend:{ip}", 20, HOUR)
    await _throttle(f"rl:resend:{data.email}", 3, HOUR)
    user = await repository.get_user_by_email(db, data.email)
    if user is not None and user.email_verified_at is None:
        token = await _issue_token(db, user, "verify_email", VERIFY_TTL)
        await db.commit()
        background.add_task(mail.send_email, user.email, *emails.verify_email(token))


async def verify_email(
    db: AsyncSession, token: str, *, ip: str | None, user_agent: str | None
) -> tuple[str, MeResponse]:
    """Confirm the address and sign the user in."""
    await _throttle(f"rl:verify:{ip}", 30, HOUR)
    now = now_utc()
    user_id = await repository.consume_auth_token(
        db, purpose="verify_email", token_hash=hash_token(token), now=now
    )
    user = await repository.get_user(db, user_id) if user_id else None
    if user is None:
        raise errors.InvalidToken(field="token")
    await repository.mark_email_verified(db, user, now)
    await _ensure_workspace(db, user)
    session_token = await _start_session(db, user, ip=ip, user_agent=user_agent)
    await db.commit()
    return session_token, await get_me(db, user)


async def forgot_password(
    db: AsyncSession, data: EmailRequest, background: BackgroundTasks, *, ip: str | None
) -> None:
    await _throttle(f"rl:forgot:{ip}", 20, HOUR)
    await _throttle(f"rl:forgot:{data.email}", 3, HOUR)
    user = await repository.get_user_by_email(db, data.email)
    if user is not None:
        token = await _issue_token(db, user, "reset_password", RESET_TTL)
        await db.commit()
        background.add_task(mail.send_email, user.email, *emails.reset_password(token))


async def reset_password(db: AsyncSession, data: ResetPasswordRequest, *, ip: str | None) -> None:
    await _throttle(f"rl:reset:{ip}", 30, HOUR)
    _check_password(data.password)  # before the token is used, so a typo does not burn the link
    now = now_utc()
    user_id = await repository.consume_auth_token(
        db, purpose="reset_password", token_hash=hash_token(data.token), now=now
    )
    user = await repository.get_user(db, user_id) if user_id else None
    if user is None:
        raise errors.InvalidToken(field="token")
    new_hash = await asyncio.to_thread(hash_password, data.password)
    await repository.update_password_hash(db, user, new_hash)
    await repository.mark_email_verified(db, user, now)  # the link proved they own the mailbox
    await repository.revoke_user_sessions(db, user.id, now)  # whoever had the old password is out
    await db.commit()


async def login_with_google(
    db: AsyncSession, profile: GoogleProfile, *, ip: str | None, user_agent: str | None
) -> str:
    """Sign in by Google id, linking an existing account with the same (Google-verified) email,
    or creating a new passwordless one. Returns the session token."""
    now = now_utc()
    user = await repository.get_user_by_google_sub(db, profile.sub)
    if user is None:
        user = await repository.get_user_by_email(db, profile.email)
        if user is None:
            user = await repository.create_user(
                db,
                email=profile.email,
                name=profile.name[:200],
                password_hash=None,
                email_verified_at=now,
                google_sub=profile.sub,
            )
        else:
            await repository.link_google(db, user, profile.sub, now)
    await _ensure_workspace(db, user)
    token = await _start_session(db, user, ip=ip, user_agent=user_agent)
    await db.commit()
    return token
