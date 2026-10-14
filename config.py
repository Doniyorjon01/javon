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

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "dev-only-secret-change-me-in-production"  # noqa: S105 — refused in production


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- general ------------------------------------------------------------
    # Required, no default: a server started without ENV must fail, not quietly run
    # as "local" with the passwordless dev sign-in switched on.
    ENV: Literal["local", "test", "staging", "production"]
    DEBUG: bool = False
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Stores live on <slug>.BASE_DOMAIN
    BASE_DOMAIN: str = "javon.uz"

    # Exact origins only (JSON list in env). Credentials are allowed, so never "*".
    # Also the CSRF allow-list: state-changing requests must come from one of these.
    CORS_ORIGINS: list[str] = []
    # Store subdomains (varaq.javon.uz) call the public storefront API from the
    # browser, e.g. r"^https://[a-z0-9-]+\.javon\.uz$". CORS only: these origins are
    # NOT trusted for cookie-authenticated writes (that is CORS_ORIGINS).
    CORS_ORIGIN_REGEX: str | None = None

    # Signs buyers' order-tracking links. Required in production (32+ characters):
    #   openssl rand -hex 32
    SECRET_KEY: SecretStr = SecretStr(DEV_SECRET_KEY)

    # Free trial for a new store, in days.
    TRIAL_DAYS: int = 14

    # Largest request body the API reads (JSON). File uploads get their own limit.
    MAX_REQUEST_BODY_BYTES: int = 1_048_576
    # Books one store may have waiting for moderation at the same time: added by
    # hand, and created by Excel imports (counted separately, see db_catalog).
    MAX_PENDING_BOOKS_PER_STORE: int = 50
    MAX_PENDING_BOOKS_FROM_IMPORT: int = 2000

    # --- files ----------------------------------------------------------------
    # Uploads (logo, covers, Excel) may be larger than ordinary JSON requests.
    MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024
    MAX_IMPORT_ROWS: int = 5000
    # Any S3-compatible store: SeaweedFS here and on the Uzbek server (services/storage.py).
    # Credentials empty = uploads are off and answer 503.
    STORAGE_ENDPOINT_URL: str = "http://localhost:9010"
    STORAGE_ACCESS_KEY: SecretStr | None = None
    STORAGE_SECRET_KEY: SecretStr | None = None
    STORAGE_REGION: str = "us-east-1"
    STORAGE_BUCKET: str = "javon-media"  # public-read: covers and logos only
    # How browsers reach that bucket (in production: Caddy or a CDN in front of it).
    STORAGE_PUBLIC_URL: str = "http://localhost:9010/javon-media"

    # Private bucket: payment receipts (they show names and card numbers). Never
    # public; the API streams a receipt only to the store's own staff.
    STORAGE_PRIVATE_BUCKET: str = "javon-private"

    # --- orders -----------------------------------------------------------------
    # Orders one IP may place in one store per window (spam guard; buyers have no account).
    ORDER_RATE_LIMIT: int = 10
    ORDER_RATE_WINDOW_S: int = 600
    # A card-transfer order with no receipt after this many hours is cancelled and
    # its books go back on the shelf (they were reserved for the buyer meanwhile).
    CARD_TRANSFER_HOLD_HOURS: int = 24

    # --- Telegram (stores' own bots) ---------------------------------------------
    # "webhook" in production (Telegram calls PUBLIC_API_URL); "polling" on a laptop,
    # where Telegram cannot reach us: run `python -m scripts.telegram_poll`.
    TELEGRAM_MODE: Literal["webhook", "polling"] = "polling"
    # Public https address of this API, as Telegram sees it (webhooks).
    PUBLIC_API_URL: str = "http://localhost:8010"
    # Fernet keys for bot tokens at rest, comma-separated, newest first (rotation:
    # put the new key in front, keep the old one until all tokens are re-saved).
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    BOT_TOKEN_KEYS: SecretStr | None = None
    TELEGRAM_API_URL: str = "https://api.telegram.org"
    # Where the store's Mini App lives ({slug} is replaced); must be https for Telegram.
    MINI_APP_URL_TEMPLATE: str = "https://{slug}.javon.uz/"
    # The store admin panel, for "open the order" buttons; https only (Telegram rule).
    ADMIN_PANEL_URL: str = "https://javon.uz/admin"
    # Buyer phone and address in Telegram messages? Telegram's servers are abroad and
    # personal data must stay in Uzbekistan (law 27-1): off until a lawyer says yes.
    TELEGRAM_ORDER_CONTACTS: bool = False
    # A Mini App sign-in (initData) older than this is refused.
    TELEGRAM_INIT_DATA_MAX_AGE_S: int = 86_400

    # --- background worker ------------------------------------------------------
    WORKER_CONCURRENCY: int = 2
    WORKER_POLL_INTERVAL_S: float = 1.0

    # --- database -----------------------------------------------------------
    DATABASE_URL: PostgresDsn
    MIGRATION_DATABASE_URL: PostgresDsn | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    # A runaway query must not hold a connection forever.
    DB_STATEMENT_TIMEOUT_MS: int = 15_000

    # --- redis --------------------------------------------------------------
    REDIS_URL: RedisDsn = Field(default="redis://localhost:6379/0", validate_default=True)

    # --- sign-in ------------------------------------------------------------
    # Token of the PLATFORM bot used by the Telegram Login Widget (not a store's bot).
    # Without it /auth/telegram answers 503.
    TELEGRAM_LOGIN_BOT_TOKEN: SecretStr | None = None
    # A widget payload older than this is refused (limits replay of a leaked payload).
    TELEGRAM_AUTH_MAX_AGE_S: int = 86_400

    SESSION_COOKIE_NAME: str = "javon_session"
    SESSION_TTL_DAYS: int = 30
    # False only for http://localhost; browsers drop Secure cookies on plain http.
    SESSION_COOKIE_SECURE: bool = True
    # ".javon.uz" in production so the Next.js server on javon.uz receives the cookie.
    SESSION_COOKIE_DOMAIN: str | None = None

    @field_validator(
        "TELEGRAM_LOGIN_BOT_TOKEN",
        "SESSION_COOKIE_DOMAIN",
        "CORS_ORIGIN_REGEX",
        "STORAGE_ACCESS_KEY",
        "STORAGE_SECRET_KEY",
        "BOT_TOKEN_KEYS",
        mode="before",
    )
    @classmethod
    def _empty_is_none(cls, v: object) -> object:
        # `X=` in .env or `${X:-}` in Compose arrives as "" — that means "not set".
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("SECRET_KEY", mode="before")
    @classmethod
    def _empty_secret_is_dev_default(cls, v: object) -> object:
        # `SECRET_KEY=` in a local .env: fall back to the dev value, which
        # production refuses (see _check_production).
        if isinstance(v, str) and not v.strip():
            return DEV_SECRET_KEY
        return v

    @model_validator(mode="after")
    def _check_production(self) -> Self:
        if self.ENV == "production":
            if self.DEBUG:
                raise ValueError("DEBUG must be false in production")
            if "*" in self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS must list exact origins in production")
            if not self.SESSION_COOKIE_SECURE:
                raise ValueError("SESSION_COOKIE_SECURE must be true in production")
            if self.TELEGRAM_LOGIN_BOT_TOKEN is None:
                raise ValueError("TELEGRAM_LOGIN_BOT_TOKEN is required in production")
            if self.BOT_TOKEN_KEYS is None:
                raise ValueError("BOT_TOKEN_KEYS is required in production")
            if self.TELEGRAM_MODE != "webhook" or not self.PUBLIC_API_URL.startswith("https://"):
                raise ValueError("production needs TELEGRAM_MODE=webhook and an https PUBLIC_API_URL")
            secret = self.SECRET_KEY.get_secret_value()
            if len(secret) < 32 or secret == DEV_SECRET_KEY:
                raise ValueError("SECRET_KEY must be set to 32+ random characters in production")
        return self

    @property
    def storage_enabled(self) -> bool:
        return self.STORAGE_ACCESS_KEY is not None and self.STORAGE_SECRET_KEY is not None

    @property
    def docs_enabled(self) -> bool:
        # OpenAPI is the contract for the frontend; expose it everywhere except production.
        return self.ENV != "production"

    @property
    def dev_login_enabled(self) -> bool:
        # Sign in as anyone without Telegram. Tests, or local development with DEBUG on:
        # two independent settings must both be wrong before it reaches a real server.
        return self.ENV == "test" or (self.ENV == "local" and self.DEBUG)


VERSION = "0.1.0"

settings = Settings()
