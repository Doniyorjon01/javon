"""
Uploaded pictures: covers and logos
===================================
    base_key = await save_image(storage, f"covers/{book_id}", data, COVER_SPEC, lang)
    # ...store base_key in the row, commit...
    await delete_image(storage, old_key, COVER_SPEC)   # after the commit

Each upload gets a NEW random key, so a picture under a key never changes and
can be cached forever; replacing a cover writes new objects and deletes the old
ones only after the database points at the new key. A failed commit deletes the
objects just written (discard_image) so nothing is left orphaned.

The database stores the base key ("covers/42/Xy3k..."); the variants are
"<base>-s.webp", "<base>-m.webp", ... (utils/images.variant_key).
"""

import asyncio
import logging
import secrets

from fastapi import UploadFile, status

from errors import generate_error
from services.storage import Storage, public_url
from translations import Msg
from utils.i18n import Lang
from utils.images import ImageRejectedError, ImageSpec, process_image, variant_key

logger = logging.getLogger(__name__)

WEBP = "image/webp"


async def read_upload(file: UploadFile, max_bytes: int, lang: Lang) -> bytes:
    """The whole upload, refusing more than max_bytes without reading it all into memory."""
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise generate_error(
            Msg.PAYLOAD_TOO_LARGE,
            lang,
            status.HTTP_413_CONTENT_TOO_LARGE,
            format_values=(max_bytes // 1024,),
        )
    if not data:
        raise generate_error(Msg.FILE_EMPTY, lang)
    return data


async def save_image(storage: Storage, prefix: str, data: bytes, spec: ImageSpec, lang: Lang) -> str:
    """Validate, convert and store all variants. Returns the new base key."""
    try:
        variants = await asyncio.to_thread(process_image, data, spec)
    except ImageRejectedError as exc:
        raise generate_error(
            Msg.IMAGE_INVALID,
            lang,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            extra={"reason": exc.problem.value},
        ) from None

    base_key = f"{prefix}/{secrets.token_urlsafe(12)}"
    keys = {name: variant_key(base_key, name) for name in variants}
    try:
        await asyncio.gather(*(storage.put(keys[name], body, WEBP) for name, body in variants.items()))
    except Exception:
        logger.exception("Storing an image failed", extra={"prefix": prefix})
        await _quiet_delete(storage, list(keys.values()))
        raise generate_error(Msg.STORAGE_UNAVAILABLE, lang, status.HTTP_503_SERVICE_UNAVAILABLE) from None
    return base_key


async def delete_image(storage: Storage, base_key: str | None, spec: ImageSpec) -> None:
    """Best effort: an orphaned file is harmless, a failed request because of one is not."""
    if base_key:
        await _quiet_delete(storage, [variant_key(base_key, name) for name in spec.widths])


async def _quiet_delete(storage: Storage, keys: list[str]) -> None:
    try:
        await storage.delete_many(keys)
    except Exception:
        logger.warning("Deleting stored objects failed", exc_info=True, extra={"count": len(keys)})


def image_urls(base_key: str | None, spec: ImageSpec) -> dict[str, str] | None:
    """{"s": url, "m": url, ...} for API responses; None when there is no picture."""
    if not base_key:
        return None
    return {name: public_url(variant_key(base_key, name)) for name in spec.widths}
