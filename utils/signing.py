"""
Signed tokens
=============
Order tracking links are capabilities: whoever has the link sees the order
status. The token is an HMAC of the order's identity with SECRET_KEY, so

  * nothing extra is stored, and the same token can be given again when the
    buyer's browser retries the checkout (idempotent replay);
  * it cannot be guessed or derived from the order number;
  * rotating SECRET_KEY invalidates every link at once.
"""

import base64
import hashlib
import hmac

from config import settings

_TOKEN_BYTES = 16  # 128 bits: plenty against guessing, short enough for a URL


def _sign(message: str) -> str:
    key = settings.SECRET_KEY.get_secret_value().encode()
    digest = hmac.new(key, message.encode(), hashlib.sha256).digest()[:_TOKEN_BYTES]
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def order_token(tenant_id: int, order_id: int) -> str:
    return _sign(f"order-tracking:{tenant_id}:{order_id}")


def check_order_token(tenant_id: int, order_id: int, token: str) -> bool:
    return hmac.compare_digest(order_token(tenant_id, order_id), token)


# --------------------------------------------------------------------------- #
# Telegram deep links
# --------------------------------------------------------------------------- #
# Telegram start parameters allow only [A-Za-z0-9_-], at most 64 characters.
_GROUP_PREFIX = "g"
_ORDER_PREFIX = "o"


def group_link_code(tenant_id: int) -> str:
    """t.me/<bot>?startgroup=<code>: adding the bot to a group with it links the group."""
    return f"{_GROUP_PREFIX}{tenant_id}_{_sign(f'telegram-group:{tenant_id}')[:16]}"


def parse_group_link_code(code: str) -> int | None:
    if not code.startswith(_GROUP_PREFIX) or "_" not in code:
        return None
    tenant_part, _, _ = code[1:].partition("_")
    if not tenant_part.isdigit():
        return None
    tenant_id = int(tenant_part)
    return tenant_id if hmac.compare_digest(group_link_code(tenant_id), code) else None


def order_start_code(tenant_id: int, order_id: int) -> str:
    """t.me/<bot>?start=<code>: the buyer of a web order gets its updates in Telegram."""
    return f"{_ORDER_PREFIX}{order_id}_{order_token(tenant_id, order_id)}"


def parse_order_start_code(tenant_id: int, code: str) -> int | None:
    if not code.startswith(_ORDER_PREFIX) or "_" not in code:
        return None
    order_part, _, token = code[1:].partition("_")
    if not order_part.isdigit():
        return None
    order_id = int(order_part)
    return order_id if check_order_token(tenant_id, order_id, token) else None
