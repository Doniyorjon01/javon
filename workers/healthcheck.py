"""
Worker healthcheck
==================
    python -m workers.healthcheck   (the `worker` healthcheck in docker-compose*.yml)

The worker (workers/main.py) touches HEARTBEAT_FILE every HEARTBEAT_INTERVAL_S
after `SELECT 1` succeeds, so a fresh file means: the process runs, its event
loop is not blocked and the database answers. Exit 0 when fresh, 1 otherwise.

Standard library only: this runs every few seconds and must start fast.
"""

import sys
import time
from pathlib import Path

HEARTBEAT_FILE = Path("/tmp/javon-worker-heartbeat")  # noqa: S108 (container-private /tmp)
HEARTBEAT_INTERVAL_S = 15.0
# Four missed beats: one slow database round-trip is not an outage.
MAX_AGE_S = HEARTBEAT_INTERVAL_S * 4


def is_fresh(path: Path = HEARTBEAT_FILE, max_age_s: float = MAX_AGE_S) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age <= max_age_s


if __name__ == "__main__":
    sys.exit(0 if is_fresh() else 1)
