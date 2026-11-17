"""All database access for auth. Never commits; the service owns the transaction."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import AuthToken, Session, User


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email))


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_user_by_google_sub(db: AsyncSession, sub: str) -> User | None:
    return await db.scalar(select(User).where(User.google_sub == sub))


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    name: str,
    password_hash: str | None,
    organization: str | None = None,
    email_verified_at: datetime | None = None,
    google_sub: str | None = None,
) -> User:
    user = User(
        email=email,
        name=name,
        password_hash=password_hash,
        organization=organization,
        email_verified_at=email_verified_at,
        google_sub=google_sub,
    )
    db.add(user)
    await db.flush()
    return user


async def update_password_hash(db: AsyncSession, user: User, password_hash: str) -> None:
    user.password_hash = password_hash
    await db.flush()


async def create_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    token_hash: str,
    ip: str | None,
    user_agent: str | None,
    now: datetime,
    expires_at: datetime,
) -> Session:
    session = Session(
        user_id=user_id,
        token_hash=token_hash,
        ip=ip,
        user_agent=user_agent,
        last_seen_at=now,
        expires_at=expires_at,
    )
    db.add(session)
    await db.flush()
    return session


async def get_active_session(db: AsyncSession, token_hash: str, now: datetime) -> Session | None:
    return await db.scalar(
        select(Session).where(
            Session.token_hash == token_hash,
            Session.revoked_at.is_(None),
            Session.expires_at > now,
        )
    )


async def touch_session(
    db: AsyncSession, session: Session, *, now: datetime, expires_at: datetime
) -> None:
    session.last_seen_at = now
    session.expires_at = expires_at
    await db.flush()


async def revoke_session_by_token(db: AsyncSession, token_hash: str, now: datetime) -> None:
    await db.execute(
        update(Session)
        .where(Session.token_hash == token_hash, Session.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def revoke_user_sessions(db: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
    await db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def issue_auth_token(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    purpose: str,
    token_hash: str,
    now: datetime,
    expires_at: datetime,
) -> None:
    """Store a new token and void the user's older unused ones of the same purpose."""
    await db.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user_id, AuthToken.purpose == purpose, AuthToken.used_at.is_(None)
        )
        .values(used_at=now)
    )
    db.add(
        AuthToken(user_id=user_id, purpose=purpose, token_hash=token_hash, expires_at=expires_at)
    )
    await db.flush()


async def consume_auth_token(
    db: AsyncSession, *, purpose: str, token_hash: str, now: datetime
) -> uuid.UUID | None:
    """Mark a valid token used and return its user. One statement, so a token works only once."""
    return await db.scalar(
        update(AuthToken)
        .where(
            AuthToken.token_hash == token_hash,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(AuthToken.user_id)
    )


async def mark_email_verified(db: AsyncSession, user: User, now: datetime) -> None:
    if user.email_verified_at is None:
        user.email_verified_at = now
        await db.flush()


async def link_google(db: AsyncSession, user: User, sub: str, now: datetime) -> None:
    user.google_sub = sub
    if user.email_verified_at is None:
        # Someone else may have opened this unverified account: drop the password they chose.
        user.password_hash = None
    await mark_email_verified(db, user, now)  # Google vouched for the address
