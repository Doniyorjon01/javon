"""
S3Storage and the bucket setup against a real S3 protocol server over HTTP.

By default an in-process moto server is used (requirements-dev.txt). To check
against the real thing, point the tests at a running SeaweedFS:

    TEST_S3_ENDPOINT_URL=http://127.0.0.1:9010 TEST_S3_ACCESS_KEY=... TEST_S3_SECRET_KEY=... pytest

Anonymous access (public read, no anonymous write) is only checked against a
real server: moto does not enforce bucket policies.
"""

import os
import secrets
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest
from botocore.exceptions import ClientError

from scripts.storage_init import ensure_bucket
from services.storage import S3Storage, create_s3_client, public_url

REAL_ENDPOINT = os.environ.get("TEST_S3_ENDPOINT_URL")


@pytest.fixture(scope="module")
def endpoint() -> Iterator[tuple[str, str, str]]:
    if REAL_ENDPOINT:
        yield REAL_ENDPOINT, os.environ["TEST_S3_ACCESS_KEY"], os.environ["TEST_S3_SECRET_KEY"]
        return
    moto_server = pytest.importorskip("moto.server")
    server = moto_server.ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}", "test", "test"
    server.stop()


@pytest.fixture(scope="module")
def bucket_client(endpoint: tuple[str, str, str]) -> tuple[Any, str]:
    url, access_key, secret_key = endpoint
    client = create_s3_client(url, access_key, secret_key)
    bucket = f"javon-test-{secrets.token_hex(4)}"
    assert ensure_bucket(client, bucket) is True
    assert ensure_bucket(client, bucket) is False  # running it again is harmless
    return client, bucket


async def test_put_and_delete(bucket_client: tuple[Any, str]) -> None:
    client, bucket = bucket_client
    storage = S3Storage(client, bucket)
    await storage.put("covers/1/abc-s.webp", b"RIFF....WEBP", "image/webp")
    await storage.put("covers/1/abc-m.webp", b"RIFF....WEBP", "image/webp")

    head = client.head_object(Bucket=bucket, Key="covers/1/abc-s.webp")
    assert head["ContentType"] == "image/webp"
    assert head["ContentLength"] == 12
    assert head["CacheControl"] == S3Storage.CACHE_CONTROL

    await storage.delete_many(["covers/1/abc-s.webp", "covers/1/abc-m.webp", "covers/1/missing.webp"])
    with pytest.raises(ClientError):
        client.head_object(Bucket=bucket, Key="covers/1/abc-s.webp")


def _anonymous(method: str, url: str) -> int:
    request = urllib.request.Request(url, data=b"x" if method == "PUT" else None, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 — test server URL
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


@pytest.mark.skipif(not REAL_ENDPOINT, reason="needs a real S3 server (TEST_S3_ENDPOINT_URL)")
async def test_bucket_is_public_read_only(
    bucket_client: tuple[Any, str], endpoint: tuple[str, str, str]
) -> None:
    client, bucket = bucket_client
    await S3Storage(client, bucket).put("logos/1/x-s.webp", b"RIFF....WEBP", "image/webp")
    base = f"{endpoint[0]}/{bucket}"
    assert _anonymous("GET", f"{base}/logos/1/x-s.webp") == 200
    assert _anonymous("GET", f"{base}?list-type=2") == 403  # no listing
    assert _anonymous("PUT", f"{base}/logos/1/evil.webp") == 403  # no anonymous upload


def test_public_url_is_built_from_settings() -> None:
    assert public_url("logos/7/x-s.webp") == "http://media.test/javon-media/logos/7/x-s.webp"
