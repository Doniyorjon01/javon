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
