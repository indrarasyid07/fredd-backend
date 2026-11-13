from functools import cached_property
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "staging", "production"] = "development"
    database_url: str
    redis_url: str

    # Public URL of the web app; requests that change data must come from this origin.
    app_base_url: str = "http://localhost:3000"
    # Extra origins accepted by the CSRF check, comma separated (e.g. the Docker Caddy port).
    allowed_origins: str = ""

    session_ttl_days: int = 30

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @cached_property
    def trusted_origins(self) -> frozenset[str]:
        extra = (o.strip().rstrip("/") for o in self.allowed_origins.split(","))
        return frozenset({self.app_base_url.rstrip("/"), *(o for o in extra if o)})


settings = Settings()  # pyright: ignore[reportCallIssue]  # values come from env
