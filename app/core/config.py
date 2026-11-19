import re
from functools import cached_property
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "staging", "production"] = "development"
    database_url: str
    redis_url: str

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, url: str) -> str:
        """Accept the plain URL that Neon and Vercel hand out and turn it into the asyncpg form."""
        url = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql+asyncpg://", url)
        if "sslmode=" in url or "channel_binding=" in url:
            url = re.sub(r"[?&](sslmode|channel_binding)=[^&]*", "", url)
            url += ("&" if "?" in url else "?") + "ssl=require"
        return url

    # Public URL of the web app; requests that change data must come from this origin.
    app_base_url: str = "http://localhost:3000"
    # Extra origins accepted by the CSRF check, comma separated (e.g. the Docker Caddy port).
    allowed_origins: str = ""

    session_ttl_days: int = 30

    # Outgoing mail. Without smtp_host, development logs the message (and its link) instead.
    smtp_host: str = ""
    smtp_port: int = 587  # STARTTLS
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Fluctuz <no-reply@fluctuz.id>"

    # Google sign-in. Empty id = the feature is off and the button answers "unavailable".
    google_client_id: str = ""
    google_client_secret: str = ""

    # Run queued jobs in the calling process instead of a worker (tests, quick local runs).
    queue_inline: bool = False

    # The platform's shared bots (B-048), shown with join codes. Empty = no share links yet.
    telegram_bot_username: str = ""  # without @, e.g. FluctuzBot
    # Bot API token and the secret Telegram echoes in X-Telegram-Bot-Api-Secret-Token.
    # Empty secret = the Telegram webhook is off (404). One bot per environment (roadmap 3.0).
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    # Linked from the consent sentence the bot sends when someone joins (UU PDP).
    privacy_policy_url: str = ""
    whatsapp_public_number: str = ""  # digits with country code, e.g. 6281100000000

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @cached_property
    def trusted_origins(self) -> frozenset[str]:
        extra = (o.strip().rstrip("/") for o in self.allowed_origins.split(","))
        return frozenset({self.app_base_url.rstrip("/"), *(o for o in extra if o)})


settings = Settings()  # pyright: ignore[reportCallIssue]  # values come from env
