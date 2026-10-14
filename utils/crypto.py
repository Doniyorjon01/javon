"""
Secrets at rest
===============
Store bot tokens (and later payment keys) are encrypted in the database with
Fernet (AES-128-CBC + HMAC-SHA256, from `cryptography`). A database dump alone
does not give anyone control of a store's bot.

Keys come from settings.BOT_TOKEN_KEYS, comma-separated, newest first:
MultiFernet encrypts with the first and decrypts with any, so rotating a key
is "prepend the new key, re-save the tokens, drop the old key".

Outside production a fixed development key is used when none is configured;
production refuses to start without real keys (config.py).
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from config import settings

# Never used in production (config refuses to start without BOT_TOKEN_KEYS there).
_DEV_KEY = "ZGV2LW9ubHkta2V5LW5vdC1mb3ItcHJvZHVjdGlvbiE="


class DecryptionError(ValueError):
    pass


@lru_cache(maxsize=1)
def _fernet() -> MultiFernet:
    raw = settings.BOT_TOKEN_KEYS.get_secret_value() if settings.BOT_TOKEN_KEYS else _DEV_KEY
    keys = [key.strip() for key in raw.split(",") if key.strip()]
    return MultiFernet([Fernet(key) for key in keys])


def encrypt(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    try:
        return _fernet().decrypt(ciphertext).decode()
    except InvalidToken:
        raise DecryptionError("cannot decrypt: wrong key or corrupted value") from None
