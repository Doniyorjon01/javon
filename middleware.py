"""
Request context middleware
==========================
Pure ASGI (not BaseHTTPMiddleware, which breaks contextvars and streaming).

For every HTTP request it:
  * assigns a request id (reuses a sane incoming X-Request-ID, e.g. from Caddy),
    exposes it to logs through `request_id_var` and returns it in the response;
  * writes one access-log line: method, path, status, duration;
  * turns any unhandled exception into our standard 500 JSON and logs the
    traceback once, with the request id attached.

The query string is deliberately NOT logged: it may carry phone numbers or
addresses, and personal data must not leave the Uzbek server (law 27-1).
"""

import logging
import re
import time
import uuid
from contextvars import ContextVar

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from translations import Msg, translate
from utils.i18n import parse_accept_language

logger = logging.getLogger("javon.request")

REQUEST_ID_HEADER = "x-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_QUIET_PATHS = ("/health",)

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming = headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)

        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception("Unhandled error on %s %s", scope["method"], scope["path"])
            if response_started:
                # Headers are already on the wire; nothing sane left to send.
                raise
            lang = parse_accept_language(headers.get("accept-language"))
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": {
                        "code": Msg.INTERNAL_ERROR.value,
                        "message": translate(Msg.INTERNAL_ERROR, lang),
                        "request_id": request_id,
                    }
                },
            )
            await response(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            level = logging.DEBUG if scope["path"].startswith(_QUIET_PATHS) else logging.INFO
            logger.log(
                level,
                "%s %s -> %s",
                scope["method"],
                scope["path"],
                status_code,
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)
