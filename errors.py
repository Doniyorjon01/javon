"""
Errors
======
Every error the API returns has one shape, so the frontend handles it in one place:

    {"detail": {"code": "<Msg value>", "message": "<text in the request language>"}}

Raise from routers and the database layer exactly as in hik-backend:

    raise generate_error(Msg.BOOK_NOT_FOUND, lang)
    raise generate_error(Msg.SLUG_TAKEN, lang, status.HTTP_409_CONFLICT, format_values=(slug,))

Unhandled exceptions are turned into a 500 of the same shape by
RequestContextMiddleware (middleware.py).
"""

import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from translations import Msg, translate
from utils.i18n import Lang, get_lang

logger = logging.getLogger(__name__)


def generate_error(
    msg: Msg,
    lang: Lang,
    status_code: int = status.HTTP_400_BAD_REQUEST,
    format_values: tuple | None = None,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    message = translate(msg, lang)
    if format_values:
        # hik passed the tuple as ONE argument ("{}".format(("a",)) -> "('a',)").
        message = message.format(*format_values)
    return HTTPException(
        status_code=status_code,
        detail={"code": msg.value, "message": message},
        headers=headers,
    )


# Framework-raised HTTP errors (unknown route, wrong method, ...) carry a plain
# string detail. Map them onto our codes so the shape never varies.
_STATUS_TO_MSG: dict[int, Msg] = {
    status.HTTP_401_UNAUTHORIZED: Msg.INVALID_CREDENTIALS,
    status.HTTP_403_FORBIDDEN: Msg.FORBIDDEN,
    status.HTTP_404_NOT_FOUND: Msg.NOT_FOUND,
    status.HTTP_405_METHOD_NOT_ALLOWED: Msg.METHOD_NOT_ALLOWED,
    status.HTTP_503_SERVICE_UNAVAILABLE: Msg.SERVICE_UNAVAILABLE,
}


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    if not (isinstance(detail, dict) and "code" in detail):
        lang = get_lang(request)
        msg = _STATUS_TO_MSG.get(exc.status_code)
        if msg is not None:
            detail = {"code": msg.value, "message": translate(msg, lang)}
        else:
            detail = {
                "code": Msg.UNKNOWN_ERROR.value,
                "message": translate(Msg.UNKNOWN_ERROR, lang).format(detail),
            }
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail},
        headers=getattr(exc, "headers", None),
    )


async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    lang = get_lang(request)
    errors = [
        # "input" echoes what the client sent (it may hold a phone number or an
        # address) and "url" points at pydantic docs; neither helps the frontend.
        {k: v for k, v in err.items() if k not in ("input", "url")}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": {
                "code": Msg.VALIDATION_ERROR.value,
                "message": translate(Msg.VALIDATION_ERROR, lang),
                "errors": jsonable_encoder(errors),
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
