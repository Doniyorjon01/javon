"""The worker heartbeat (workers/main.py) and its container healthcheck (workers/healthcheck.py)."""

import os
import time
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from workers import healthcheck
from workers import main as worker


def test_missing_file_is_unhealthy(tmp_path: Path) -> None:
    assert not healthcheck.is_fresh(tmp_path / "beat")


def test_recent_beat_is_healthy_and_old_one_is_not(tmp_path: Path) -> None:
    beat = tmp_path / "beat"
    beat.touch()
    assert healthcheck.is_fresh(beat)

    old = time.time() - healthcheck.MAX_AGE_S - 1
    os.utime(beat, (old, old))
    assert not healthcheck.is_fresh(beat)


@pytest.mark.db
async def test_beat_touches_the_file_when_the_database_answers(
    owner_engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beat = tmp_path / "beat"
    monkeypatch.setattr(worker, "HEARTBEAT_FILE", beat)
    await worker.beat()
    assert healthcheck.is_fresh(beat)


async def test_no_beat_when_the_database_is_down(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class DownSession:
        async def __aenter__(self) -> "DownSession":
            raise ConnectionRefusedError

        async def __aexit__(self, *exc: object) -> None:
            return None

    beat = tmp_path / "beat"
    monkeypatch.setattr(worker, "HEARTBEAT_FILE", beat)
    monkeypatch.setattr(worker, "SessionLocal", DownSession)
    with pytest.raises(ConnectionRefusedError):
        await worker.beat()
    assert not beat.exists()
