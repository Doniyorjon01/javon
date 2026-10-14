"""
Prepare the file storage bucket
===============================
    python -m scripts.storage_init      (the `storage-init` service in docker-compose.yml)

Creates STORAGE_BUCKET if it does not exist and gives it the public-read policy:
anyone may download a cover or a logo, nobody anonymous may list, upload or
delete. Creates STORAGE_PRIVATE_BUCKET (payment receipts) with NO policy: only
our credentials can read it. Safe to run any number of times.
"""

import sys

from botocore.exceptions import ClientError

from config import settings
from services.storage import create_s3_client, public_read_policy


def ensure_bucket(client: object, bucket: str, *, public: bool = True) -> bool:
    """True if the bucket was created now."""
    created = False
    try:
        client.head_bucket(Bucket=bucket)  # type: ignore[attr-defined]
    except ClientError:
        client.create_bucket(Bucket=bucket)  # type: ignore[attr-defined]
        created = True
    if public:
        client.put_bucket_policy(Bucket=bucket, Policy=public_read_policy(bucket))  # type: ignore[attr-defined]
    return created


def main() -> int:
    if not settings.storage_enabled:
        print("STORAGE_ACCESS_KEY / STORAGE_SECRET_KEY are not set; nothing to do", file=sys.stderr)
        return 1
    client = create_s3_client(
        settings.STORAGE_ENDPOINT_URL,
        settings.STORAGE_ACCESS_KEY.get_secret_value(),  # type: ignore[union-attr]
        settings.STORAGE_SECRET_KEY.get_secret_value(),  # type: ignore[union-attr]
        settings.STORAGE_REGION,
    )
    created = ensure_bucket(client, settings.STORAGE_BUCKET)
    print(f"bucket {settings.STORAGE_BUCKET}: {'created' if created else 'exists'}, public read policy set")
    created = ensure_bucket(client, settings.STORAGE_PRIVATE_BUCKET, public=False)
    print(f"bucket {settings.STORAGE_PRIVATE_BUCKET}: {'created' if created else 'exists'}, private")
    return 0


if __name__ == "__main__":
    sys.exit(main())
