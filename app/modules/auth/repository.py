"""All database access for auth. Never commits; the service owns the transaction."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Session, User


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email))


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def create_user(db: AsyncSession, *, email: str, name: str, password_hash: str) -> User:
    user = User(email=email, name=name, password_hash=password_hash)
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
