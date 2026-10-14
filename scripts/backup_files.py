"""
File backup: mirror the buckets to a folder
===========================================
    python -m scripts.backup_files /backups/files           once
    python -m scripts.backup_files /backups/files --loop    every BACKUP_INTERVAL_S (the
                                                            `backup-files` service)

Copies every object of STORAGE_BUCKET (covers, logos) and STORAGE_PRIVATE_BUCKET
(payment receipts) to <folder>/<bucket>/<key>. Keys never get new content (each
upload makes a new key), so a file already there with the same size is skipped:
after the first run only new uploads are copied. Files whose object was deleted
are deleted here too, so a removed receipt does not live on in the backup.

Files are written as *.part and renamed, so an interrupted run leaves no broken
file under a real name. The folder stays on the server (Uzbekistan); copy it to
a second server there as well.
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from config import settings
from services.storage import create_s3_client
from utils.log import configure_logging

logger = logging.getLogger("javon.backup_files")


def mirror_bucket(client: object, bucket: str, target: Path) -> dict[str, int]:
    counts = {"copied": 0, "kept": 0, "removed": 0}
    seen: set[Path] = set()
    paginator = client.get_paginator("list_objects_v2")  # type: ignore[attr-defined]
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            path = (target / key).resolve()
            if target.resolve() not in path.parents:  # a key like "../x" must not escape
                logger.warning("Skipped a key outside the backup folder", extra={"bucket": bucket})
                continue
            seen.add(path)
            if path.is_file() and path.stat().st_size == obj["Size"]:
                counts["kept"] += 1
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            part = path.with_name(path.name + ".part")
            client.download_file(bucket, key, str(part))  # type: ignore[attr-defined]
            os.replace(part, path)
            counts["copied"] += 1
    if target.exists():
        for path in target.rglob("*"):
            if path.is_file() and path.resolve() not in seen:
                path.unlink()
                counts["removed"] += 1
    return counts


def backup_once(folder: Path) -> None:
    if not settings.storage_enabled:
        raise SystemExit("STORAGE_ACCESS_KEY / STORAGE_SECRET_KEY are not set")
    client = create_s3_client(
        settings.STORAGE_ENDPOINT_URL,
        settings.STORAGE_ACCESS_KEY.get_secret_value(),  # type: ignore[union-attr]
        settings.STORAGE_SECRET_KEY.get_secret_value(),  # type: ignore[union-attr]
        settings.STORAGE_REGION,
    )
    for bucket in (settings.STORAGE_BUCKET, settings.STORAGE_PRIVATE_BUCKET):
        counts = mirror_bucket(client, bucket, folder / bucket)
        logger.info("Bucket mirrored", extra={"bucket": bucket, **counts})


def main() -> None:
    configure_logging(settings.LOG_LEVEL)
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    interval = int(os.environ.get("BACKUP_INTERVAL_S", "86400"))
    while True:
        try:
            backup_once(args.folder)
        except Exception:
            logger.exception("File backup failed")
            if not args.loop:
                sys.exit(1)
        if not args.loop:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
