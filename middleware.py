"""
Middlewares
===========
RequestContextMiddleware, BodySizeLimitMiddleware and StorefrontCORSMiddleware.

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
from starlette.exceptions import HTTPException as StarletteHTTPException
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


class BodySizeLimitMiddleware:
    """
    Refuses request bodies larger than `max_bytes` with our standard 413 JSON,
    before the application reads them into memory.

      * Content-Length too big   -> answered at once, the body is never read;
      * no Content-Length (chunked) -> bytes are counted as they arrive and the
        read is stopped at the limit.

    Paths matching `upload_paths` (logo, cover and Excel uploads) get the larger
    `upload_max_bytes` instead; everything else is JSON and stays small.
    """

    def __init__(
        self,
        app: ASGIApp,
        max_bytes: int,
        upload_max_bytes: int | None = None,
        upload_paths: re.Pattern[str] | None = None,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.upload_max_bytes = upload_max_bytes or max_bytes
        self.upload_paths = upload_paths

    def _limit_for(self, path: str) -> int:
        if self.upload_paths is not None and self.upload_paths.match(path):
            return self.upload_max_bytes
        return self.max_bytes

    @staticmethod
    def _detail(headers: Headers, limit: int) -> dict[str, str]:
        lang = parse_accept_language(headers.get("accept-language"))
        message = translate(Msg.PAYLOAD_TOO_LARGE, lang).format(limit // 1024)
        return {"code": Msg.PAYLOAD_TOO_LARGE.value, "message": message}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        limit = self._limit_for(scope["path"])
        declared = headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            response = JSONResponse(status_code=413, content={"detail": self._detail(headers, limit)})
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # An HTTPException, so FastAPI's body reader re-raises it as is and
                    # our exception handler returns it in the standard shape.
                    raise StarletteHTTPException(status_code=413, detail=self._detail(headers, limit))
            return message

        await self.app(scope, limited_receive, send)


class StorefrontCORSMiddleware:
    """
    CORS for the PUBLIC storefront API, called from store subdomains
    (varaq.javon.uz) straight from the buyer's browser.

    Deliberately separate from the main CORSMiddleware: store subdomains get
    read access and checkout on /storefront/* only, and NEVER credentials (no
    cookie-authenticated requests), whatever the inner layers added.
    Origins listed in CORS_ORIGINS (our own frontend) are left to the main one.
    """

    ALLOW_METHODS = "GET, POST"
    ALLOW_HEADERS = "Content-Type, Accept-Language"
    EXPOSE_HEADERS = "X-Request-ID, Retry-After"

    def __init__(self, app: ASGIApp, origin_regex: str, trusted_origins: list[str]) -> None:
        self.app = app
        self.pattern = re.compile(origin_regex)
        self.trusted = frozenset(trusted_origins)

    def _handles(self, scope: Scope, origin: str | None) -> bool:
        return (
            scope["path"].startswith("/storefront/")
            and origin is not None
            and origin not in self.trusted
            and self.pattern.fullmatch(origin) is not None
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if not self._handles(scope, origin):
            await self.app(scope, receive, send)
            return

        if scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
            preflight = JSONResponse(
                {},
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": self.ALLOW_METHODS,
                    "Access-Control-Allow-Headers": self.ALLOW_HEADERS,
                    "Access-Control-Max-Age": "600",
                    "Vary": "Origin",
                },
            )
            await preflight(scope, receive, send)
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name in ("access-control-allow-credentials", "access-control-allow-origin"):
                    if name in response_headers:
                        del response_headers[name]
                response_headers["Access-Control-Allow-Origin"] = origin
                response_headers["Access-Control-Expose-Headers"] = self.EXPOSE_HEADERS
                response_headers.add_vary_header("Origin")
            await send(message)

        await self.app(scope, receive, send_with_cors)
