"""Google sign-in: authorization code flow with PKCE, no extra dependency beyond httpx.

The one-time state and PKCE verifier live in Redis for 10 minutes; the browser only holds the
state in a short-lived cookie, so there is nothing to forge or sign.
"""

import base64
import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.core.redis import redis
from app.core.security import new_token
from app.modules.auth.errors import GoogleError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
STATE_TTL_SECONDS = 600


@dataclass(frozen=True)
class GoogleProfile:
    sub: str
    email: str
    name: str


def redirect_uri() -> str:
    return f"{settings.app_base_url.rstrip('/')}/api/v1/auth/google/callback"


def safe_next(next_path: str | None) -> str:
    """Same-site dashboard paths only; anything else becomes /app (no open redirect)."""
    ok = next_path and next_path.startswith("/app") and not next_path.startswith("//")
    return next_path if ok and next_path and "\\" not in next_path else "/app"


async def start(next_path: str | None) -> tuple[str, str]:
    """Return the Google URL to send the browser to, and the state for the cookie."""
    if not settings.google_client_id:
        raise GoogleError("google_unavailable")
    state, verifier = new_token(), new_token()
    await redis.set(
        f"oauth:google:{state}",
        json.dumps({"verifier": verifier, "next": safe_next(next_path)}),
        ex=STATE_TTL_SECONDS,
    )
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": redirect_uri(),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": challenge.decode(),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return f"{AUTH_URL}?{query}", state


async def finish(
    code: str | None, state: str | None, cookie_state: str | None
) -> tuple[GoogleProfile, str]:
    """Check the state, trade the code for the profile, return it with the page to land on."""
    if not code or not state or state != cookie_state:
        raise GoogleError("google_failed")
    saved = await redis.getdel(f"oauth:google:{state}")  # single use
    if saved is None:
        raise GoogleError("google_failed")
    data = json.loads(saved)
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            token = await http.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": redirect_uri(),
                    "grant_type": "authorization_code",
                    "code_verifier": data["verifier"],
                },
            )
            token.raise_for_status()
            info = await http.get(
                USERINFO_URL,
                headers={"Authorization": f"Bearer {token.json()['access_token']}"},
            )
            info.raise_for_status()
            profile = info.json()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise GoogleError("google_failed") from exc
    if not profile.get("email_verified") or not profile.get("sub") or not profile.get("email"):
        raise GoogleError("google_failed")
    email = str(profile["email"]).strip().lower()
    return GoogleProfile(
        str(profile["sub"]), email, str(profile.get("name") or email.split("@")[0])
    ), data["next"]
