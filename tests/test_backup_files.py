"""The file backup mirrors both buckets incrementally and follows deletions."""

from pathlib import Path

import pytest

from scripts.backup_files import mirror_bucket

moto = pytest.importorskip("moto")


@pytest.fixture
def s3() -> object:
    import boto3

    with moto.mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="javon-private")
        yield client


def test_mirror_copies_new_files_and_follows_deletions(s3: object, tmp_path: Path) -> None:
    s3.put_object(Bucket="javon-private", Key="receipts/1/5/a-l.webp", Body=b"first")  # type: ignore[attr-defined]
    s3.put_object(Bucket="javon-private", Key="receipts/1/6/b-l.webp", Body=b"second")  # type: ignore[attr-defined]
    target = tmp_path / "javon-private"

    assert mirror_bucket(s3, "javon-private", target) == {"copied": 2, "kept": 0, "removed": 0}
    assert (target / "receipts/1/5/a-l.webp").read_bytes() == b"first"

    s3.delete_object(Bucket="javon-private", Key="receipts/1/5/a-l.webp")  # type: ignore[attr-defined]
    s3.put_object(Bucket="javon-private", Key="receipts/2/9/c-l.webp", Body=b"third")  # type: ignore[attr-defined]
    assert mirror_bucket(s3, "javon-private", target) == {"copied": 1, "kept": 1, "removed": 1}
    assert not (target / "receipts/1/5/a-l.webp").exists()
    assert not list(target.rglob("*.part"))
