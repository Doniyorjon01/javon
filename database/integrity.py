"""
IntegrityError helpers
======================
Concurrent requests can both pass an "is it free?" check; the UNIQUE constraint
is the real guard. Catch the IntegrityError and map the constraint name to a
user-facing error instead of returning a 500.
"""

from sqlalchemy.exc import IntegrityError


def constraint_name(exc: IntegrityError) -> str | None:
    # SQLAlchemy wraps the asyncpg error; the original carries `constraint_name`.
    for err in (exc.orig, getattr(exc.orig, "__cause__", None)):
        name = getattr(err, "constraint_name", None)
        if name:
            return name
    return None
