"""
Application configuration.

Instead of hardcoding one full DATABASE_URL, we read the individual
pieces (user, password, host, port, db name) from .env and BUILD the
connection string ourselves. This means if you ever change the database
name, you only change it in ONE place (POSTGRES_DB) — the URL updates
itself automatically.
"""

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Individual pieces, read straight from .env
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str = "db"      # "db" matches the docker-compose service name
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str

    APP_ENV: str = "local"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        """Build the full SQLAlchemy connection string from the pieces above."""
        return (
            f"postgresql+psycopg://"
            f"{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}"
            f"/{self.POSTGRES_DB}"
        )


# Instantiated once, imported everywhere else.
settings = Settings()