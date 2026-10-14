"""
Error tracking without personal data
====================================
    init_sentry("api")      in main.create_app()
    init_sentry("worker")   in workers/main.py

Off unless SENTRY_DSN is set. Sentry's servers are abroad and the personal-data
law (27-1) keeps buyers' data in Uzbekistan, so what leaves is the error and its
stack trace, nothing about the person:

  * send_default_pii=False, no local variables, no request bodies;
  * every event's request is cut down to method + path (no query string: order
    tracking tokens live there; no headers: cookies and init data live there);
  * no user, no breadcrumbs from HTTP clients (a Telegram API URL contains the
    bot token), and the httpx integration is disabled altogether;
  * anything shaped like a bot token left in a message is masked.

A self-hosted GlitchTip in Uzbekistan accepts the same DSN format if even this
much should not leave the country.
"""

import logging
import re
from typing import Any

from config import VERSION, settings

logger = logging.getLogger(__name__)

# No leading \b: in a Telegram URL the token follows "bot" directly (".../bot123:AA...").
_BOT_TOKEN = re.compile(r"(?<![0-9])\d{5,15}:[A-Za-z0-9_-]{30,60}")
_DROP_BREADCRUMBS = frozenset({"httplib", "http", "redis", "query"})


def _mask(value: Any) -> Any:
    if isinstance(value, str):
        return _BOT_TOKEN.sub("<bot-token>", value)
    if isinstance(value, dict):
        return {key: _mask(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask(item) for item in value]
    return value


def scrub_event(event: dict[str, Any], _hint: dict[str, Any] | None = None) -> dict[str, Any]:
    request = event.get("request")
    if isinstance(request, dict):
        url = str(request.get("url", "")).split("?")[0]
        event["request"] = {"method": request.get("method"), "url": url}
    event.pop("user", None)
    event.pop("server_name", None)
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        breadcrumbs["values"] = [
            crumb for crumb in breadcrumbs.get("values", []) if crumb.get("category") not in _DROP_BREADCRUMBS
        ]
    return _mask(event)


def scrub_breadcrumb(crumb: dict[str, Any], _hint: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if crumb.get("category") in _DROP_BREADCRUMBS:
        return None
    crumb.pop("data", None)
    return _mask(crumb)


def init_sentry(component: str) -> bool:
    dsn = settings.SENTRY_DSN
    if dsn is None:
        return False
    import sentry_sdk
    from sentry_sdk.integrations.httpx import HttpxIntegration

    sentry_sdk.init(
        dsn=dsn.get_secret_value(),
        environment=settings.ENV,
        release=f"javon@{VERSION}",
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        disabled_integrations=[HttpxIntegration()],
        before_send=scrub_event,
        before_send_transaction=scrub_event,
        before_breadcrumb=scrub_breadcrumb,
    )
    sentry_sdk.set_tag("component", component)
    logger.info("Sentry enabled", extra={"component": component})
    return True
