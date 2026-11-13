from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "staging", "production"] = "development"
    database_url: str
    redis_url: str


settings = Settings()  # pyright: ignore[reportCallIssue]  # values come from env
