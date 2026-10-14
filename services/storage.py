"""
File storage (S3 API)
=====================
Book covers and store logos live in a public-read bucket on our own server in
Uzbekistan; payment receipts in a second, private one (STORAGE_PRIVATE_BUCKET),
which only the API reads (it streams a receipt to the store's staff). The
database stores only the object KEY, never a URL: moving to another host or
putting a CDN in front changes STORAGE_PUBLIC_URL, not the data.

The server is SeaweedFS (docker-compose.yml): Apache-2.0 and maintained. MinIO,
named in the original plan, stopped publishing community builds in October 2025
and its repository was archived in April 2026. We talk plain S3 through boto3,
so SeaweedFS, Garage or a cloud bucket are interchangeable by configuration.

Routes and the database layer depend on the small `Storage` protocol, never on
boto3, so tests use MemoryStorage (and tests/test_storage_s3.py checks
S3Storage against a real S3 protocol server).

boto3 is synchronous, so every call runs in a worker thread: async code must not
block the event loop. One client per process (boto3 clients are thread-safe),
created in main.lifespan and kept on app.state.storage.
"""

import asyncio
import json
import logging
from typing import Any, Protocol

import boto3
from botocore.config import Config
from fastapi import Request, status

from config import settings
from errors import generate_error
from translations import Msg
from utils.i18n import get_lang

logger = logging.getLogger(__name__)


class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def delete_many(self, keys: list[str]) -> None:
        """Best effort; a missing key is not an error."""
        ...

    async def get(self, key: str) -> bytes | None:
        """The object's bytes, or None if there is no such key."""
        ...


def public_url(key: str) -> str:
    return f"{settings.STORAGE_PUBLIC_URL.rstrip('/')}/{key}"


def public_read_policy(bucket: str) -> str:
    """Anyone may GET an object; nobody anonymous may list, write or delete."""
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "PublicReadObjects",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket}/*"],
                }
            ],
        }
    )


def create_s3_client(endpoint_url: str, access_key: str, secret_key: str, region: str = "us-east-1") -> Any:
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},  # http://host/bucket/key: no wildcard DNS needed
            connect_timeout=3,
            read_timeout=20,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


class S3Storage:
    # A key never gets new content (a new upload gets a new key), so browsers and a
    # CDN may cache for a year.
    CACHE_CONTROL = "public, max-age=31536000, immutable"

    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, bucket: str | None = None) -> "S3Storage":
        if settings.STORAGE_ACCESS_KEY is None or settings.STORAGE_SECRET_KEY is None:
            raise RuntimeError("STORAGE_ACCESS_KEY and STORAGE_SECRET_KEY are not set")
        client = create_s3_client(
            settings.STORAGE_ENDPOINT_URL,
            settings.STORAGE_ACCESS_KEY.get_secret_value(),
            settings.STORAGE_SECRET_KEY.get_secret_value(),
            settings.STORAGE_REGION,
        )
        return cls(client, bucket or settings.STORAGE_BUCKET)

    async def get(self, key: str) -> bytes | None:
        def _get() -> bytes | None:
            try:
                response = self._client.get_object(Bucket=self._bucket, Key=key)
            except self._client.exceptions.NoSuchKey:
                return None
            return response["Body"].read()

        return await asyncio.to_thread(_get)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl=self.CACHE_CONTROL,
        )

    async def delete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        result = await asyncio.to_thread(
            self._client.delete_objects,
            Bucket=self._bucket,
            Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
        )
        for error in result.get("Errors", []):
            logger.warning("Could not delete stored object", extra={"key": error.get("Key")})


class MemoryStorage:
    """For tests: keeps objects in a dict."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def delete_many(self, keys: list[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)

    async def get(self, key: str) -> bytes | None:
        found = self.objects.get(key)
        return found[0] if found else None


def create_storage(bucket: str | None = None) -> Storage | None:
    """None when storage credentials are not configured: upload routes answer 503."""
    return S3Storage.from_settings(bucket) if settings.storage_enabled else None


def get_storage(request: Request) -> Storage:
    """Route dependency. 503 storage_unavailable when no storage is configured."""
    storage: Storage | None = getattr(request.app.state, "storage", None)
    if storage is None:
        raise generate_error(Msg.STORAGE_UNAVAILABLE, get_lang(request), status.HTTP_503_SERVICE_UNAVAILABLE)
    return storage


def get_private_storage(request: Request) -> Storage:
    """The private bucket (payment receipts). 503 when not configured."""
    storage: Storage | None = getattr(request.app.state, "private_storage", None)
    if storage is None:
        raise generate_error(Msg.STORAGE_UNAVAILABLE, get_lang(request), status.HTTP_503_SERVICE_UNAVAILABLE)
    return storage
