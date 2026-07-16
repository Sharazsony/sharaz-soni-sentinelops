"""
Application configuration.

Reads ONLY the three keys the FastAPI app itself needs:
    - DATABASE_URL
    - APP_ENV
    - LOG_LEVEL

It deliberately does NOT read POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB
those are consumed by the `db` container's own postgres entrypoint, never by
this Settings class. See .env.example for the split.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    APP_ENV: str = "local"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Instantiated once, imported everywhere else.
settings = Settings()
