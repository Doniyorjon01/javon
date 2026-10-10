"""
Application settings
====================
Every value comes from the environment (or .env when running locally).
Import the ready instance: `from config import settings`.

Two database URLs on purpose:
    DATABASE_URL            javon_app   — the role the API runs as. Owns no tables, so
                                          Row Level Security policies always apply to it.
    MIGRATION_DATABASE_URL  javon_owner — owns the schema; only Alembic uses it.
If the API ran as the table owner, RLS would be silently skipped.
"""

from typing import Literal, Self

from pydantic import Field, PostgresDsn, RedisDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- general ------------------------------------------------------------
    ENV: Literal["local", "test", "staging", "production"] = "local"
    DEBUG: bool = False
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Stores live on <slug>.BASE_DOMAIN
    BASE_DOMAIN: str = "javon.uz"

    # Exact origins only (JSON list in env). Credentials are allowed, so never "*".
    CORS_ORIGINS: list[str] = []

    # --- database -----------------------------------------------------------
    DATABASE_URL: PostgresDsn
    MIGRATION_DATABASE_URL: PostgresDsn | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    # A runaway query must not hold a connection forever.
    DB_STATEMENT_TIMEOUT_MS: int = 15_000

    # --- redis --------------------------------------------------------------
    REDIS_URL: RedisDsn = Field(default="redis://localhost:6379/0", validate_default=True)

    @model_validator(mode="after")
    def _check_production(self) -> Self:
        if self.ENV == "production":
            if self.DEBUG:
                raise ValueError("DEBUG must be false in production")
            if "*" in self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS must list exact origins in production")
        return self

    @property
    def docs_enabled(self) -> bool:
        # OpenAPI is the contract for the frontend; expose it everywhere except production.
        return self.ENV != "production"


VERSION = "0.1.0"

settings = Settings()
