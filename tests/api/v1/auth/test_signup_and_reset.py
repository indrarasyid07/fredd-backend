import re
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.modules.auth.models import AuthToken, Session, User
from tests.conftest import PASSWORD

BASE = "/api/v1/auth"
SIGNUP = {
    "first_name": "Budi",
    "last_name": "Santoso",
    "email": "budi@contoh.id",
    "organization": "Dinas Pertanian",
    "password": "rahasia123",
    "accept_terms": True,
}


def _token(outbox: list[tuple[str, str, str]]) -> str:
    match = re.search(r"token=([\w-]+)", outbox[-1][2])
    assert match
    return match.group(1)


async def _get_user(db: AsyncSession, email: str) -> User:
    return (await db.scalars(select(User).where(User.email == email))).one()


async def test_register_then_verify_signs_in(
    client: AsyncClient, db: AsyncSession, outbox: list[tuple[str, str, str]]
) -> None:
    response = await client.post(f"{BASE}/register", json=SIGNUP)
    assert response.status_code == 200
    assert response.json()["data"] is None
    user = await _get_user(db, "budi@contoh.id")
    assert (user.name, user.organization, user.email_verified_at) == (
        "Budi Santoso",
        "Dinas Pertanian",
        None,
    )
    assert len(outbox) == 1 and outbox[0][0] == "budi@contoh.id"

    # Not signed in yet: the password is right but the email is unverified.
    login = await client.post(
        f"{BASE}/login", json={"email": "budi@contoh.id", "password": SIGNUP["password"]}
    )
    assert (login.status_code, login.json()["errors"][0]["code"]) == (403, "email_not_verified")

    token = _token(outbox)
    verified = await client.post(f"{BASE}/verify-email", json={"token": token})
    assert verified.status_code == 200
    assert "fluctuz_session=" in verified.headers["set-cookie"]
    assert (await client.get(f"{BASE}/me")).status_code == 200
    await db.refresh(user)
    assert user.email_verified_at is not None

    again = await client.post(f"{BASE}/verify-email", json={"token": token})
    assert (again.status_code, again.json()["errors"][0]["code"]) == (400, "invalid_token")


async def test_register_existing_email_looks_the_same_and_warns_the_owner(
    client: AsyncClient, user: User, outbox: list[tuple[str, str, str]]
) -> None:
    response = await client.post(f"{BASE}/register", json={**SIGNUP, "email": user.email})

    assert response.status_code == 200
    assert (
        response.json()["message"]
        == (await client.post(f"{BASE}/register", json=SIGNUP)).json()["message"]
    )
    assert outbox[0][0] == user.email and "token=" not in outbox[0][2]


async def test_register_again_before_verifying_voids_the_old_link(
    client: AsyncClient, outbox: list[tuple[str, str, str]]
) -> None:
    await client.post(f"{BASE}/register", json=SIGNUP)
    first = _token(outbox)
    await client.post(f"{BASE}/register", json=SIGNUP)

    assert _token(outbox) != first
    stale = await client.post(f"{BASE}/verify-email", json={"token": first})
    assert stale.status_code == 400


async def test_register_validation(client: AsyncClient, outbox: list[tuple[str, str, str]]) -> None:
    weak = await client.post(f"{BASE}/register", json={**SIGNUP, "password": "pendek1"})
    assert (weak.status_code, weak.json()["errors"][0]["code"]) == (422, "weak_password")

    no_terms = await client.post(f"{BASE}/register", json={**SIGNUP, "accept_terms": False})
    error = no_terms.json()["errors"][0]
    assert (no_terms.status_code, error["code"], error["field"]) == (
        422,
        "terms_not_accepted",
        "accept_terms",
    )
    assert outbox == []


async def test_resend_only_mails_unverified_accounts_and_is_rate_limited(
    client: AsyncClient, user: User, outbox: list[tuple[str, str, str]]
) -> None:
    await client.post(f"{BASE}/register", json=SIGNUP)
    outbox.clear()

    unknown = await client.post(f"{BASE}/verify-email/resend", json={"email": "x@contoh.id"})
    verified = await client.post(f"{BASE}/verify-email/resend", json={"email": user.email})
    assert (unknown.status_code, verified.status_code) == (200, 200)
    assert outbox == []

    unverified = {"email": SIGNUP["email"]}
    for _ in range(3):  # the unknown/verified calls above used other emails
        assert (
            await client.post(f"{BASE}/verify-email/resend", json=unverified)
        ).status_code == 200
    assert len(outbox) == 3
    blocked = await client.post(f"{BASE}/verify-email/resend", json=unverified)
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers


async def test_password_reset_changes_password_and_revokes_sessions(
    logged_in: AsyncClient, user: User, db: AsyncSession, outbox: list[tuple[str, str, str]]
) -> None:
    unknown = await logged_in.post(f"{BASE}/password/forgot", json={"email": "x@contoh.id"})
    assert unknown.status_code == 200 and outbox == []

    await logged_in.post(f"{BASE}/password/forgot", json={"email": user.email})
    token = _token(outbox)

    weak = await logged_in.post(f"{BASE}/password/reset", json={"token": token, "password": "abc"})
    assert (weak.status_code, weak.json()["errors"][0]["code"]) == (422, "weak_password")

    done = await logged_in.post(
        f"{BASE}/password/reset", json={"token": token, "password": "baru12345"}
    )
    assert done.status_code == 200  # the weak attempt above did not burn the token
    assert (await logged_in.get(f"{BASE}/me")).status_code == 401  # old session is gone
    revoked = await db.scalars(select(Session.revoked_at).where(Session.user_id == user.id))
    assert all(r is not None for r in revoked)

    old = await logged_in.post(f"{BASE}/login", json={"email": user.email, "password": PASSWORD})
    new = await logged_in.post(f"{BASE}/login", json={"email": user.email, "password": "baru12345"})
    assert (old.status_code, new.status_code) == (401, 200)

    reused = await logged_in.post(
        f"{BASE}/password/reset", json={"token": token, "password": "lain12345"}
    )
    assert reused.status_code == 400


async def test_reset_rejects_expired_and_unknown_tokens(
    client: AsyncClient, user: User, db: AsyncSession, outbox: list[tuple[str, str, str]]
) -> None:
    await client.post(f"{BASE}/password/forgot", json={"email": user.email})
    await db.execute(update(AuthToken).values(expires_at=now_utc() - timedelta(seconds=1)))

    for token in (_token(outbox), "tidak-ada"):
        response = await client.post(
            f"{BASE}/password/reset", json={"token": token, "password": "baru12345"}
        )
        assert (response.status_code, response.json()["errors"][0]["code"]) == (
            400,
            "invalid_token",
        )


async def test_forgot_password_is_rate_limited_per_email(
    client: AsyncClient, user: User, outbox: list[tuple[str, str, str]]
) -> None:
    for _ in range(3):
        assert (
            await client.post(f"{BASE}/password/forgot", json={"email": user.email})
        ).status_code == 200
    assert (
        await client.post(f"{BASE}/password/forgot", json={"email": user.email})
    ).status_code == 429
    assert len(outbox) == 3
