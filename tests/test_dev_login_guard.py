"""The no-Telegram sign-in must not exist outside local development and tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from config import Settings, settings
from main import create_app


@pytest.mark.parametrize(
    ("env", "debug", "expected_status"),
    [  # 422 = the route exists and rejected the empty body; 404 = no such route
        ("local", True, 422),
        ("local", False, 404),  # a server left on ENV=local but not in debug mode
        ("test", False, 422),
        ("staging", True, 404),
        ("production", False, 404),
    ],
)
async def test_dev_login_route_only_in_dev(
    monkeypatch: pytest.MonkeyPatch, env: str, debug: bool, expected_status: int
) -> None:
    monkeypatch.setattr(settings, "ENV", env)
    monkeypatch.setattr(settings, "DEBUG", debug)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        resp = await http.post("/auth/dev-login", json={})
    assert resp.status_code == expected_status


def test_env_must_be_set_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    """No default: a server started without ENV must not quietly run as "local"."""
    monkeypatch.delenv("ENV", raising=False)
    with pytest.raises(ValueError, match="ENV"):
        Settings(_env_file=None, DATABASE_URL="postgresql+asyncpg://a:b@localhost/x")


def test_production_settings_refuse_dev_conveniences() -> None:
    base = {
        "_env_file": None,  # the developer's .env (DEBUG=true etc.) must not leak in
        "DATABASE_URL": "postgresql+asyncpg://a:b@localhost/x",
        "ENV": "production",
        "DEBUG": False,
    }
    with pytest.raises(ValueError, match="SESSION_COOKIE_SECURE"):
        Settings(**base, TELEGRAM_LOGIN_BOT_TOKEN="1:x", SESSION_COOKIE_SECURE=False)
    with pytest.raises(ValueError, match="TELEGRAM_LOGIN_BOT_TOKEN"):
        Settings(**base, TELEGRAM_LOGIN_BOT_TOKEN=None, SESSION_COOKIE_SECURE=True)


def test_empty_token_in_env_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """`TELEGRAM_LOGIN_BOT_TOKEN=` (empty) must not satisfy the production check."""
    monkeypatch.setenv("TELEGRAM_LOGIN_BOT_TOKEN", "")
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("CORS_ORIGINS", "[]")
    with pytest.raises(ValueError, match="TELEGRAM_LOGIN_BOT_TOKEN"):
        Settings(_env_file=None)


def test_production_needs_a_real_secret_key() -> None:
    base = {
        "_env_file": None,
        "DATABASE_URL": "postgresql+asyncpg://a:b@localhost/x",
        "ENV": "production",
        "DEBUG": False,
        "TELEGRAM_LOGIN_BOT_TOKEN": "1:x",
        "SESSION_COOKIE_SECURE": True,
    }
    for weak in ("", "short", "dev-only-secret-change-me-in-production"):
        with pytest.raises(ValueError, match="SECRET_KEY"):
            Settings(**base, SECRET_KEY=weak)
    assert Settings(**base, SECRET_KEY="x" * 64).SECRET_KEY.get_secret_value() == "x" * 64
