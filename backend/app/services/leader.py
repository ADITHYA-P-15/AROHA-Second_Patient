"""Only one instance runs the scheduler tick, so a rolling or overlapping deploy cannot double-send alerts or double-escalate."""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import text

from app.core.db import engine

LOCK_KEY = 7_204_001  # arbitrary application-wide number


@contextmanager
def scheduler_lease():
    """Yields True when this process holds the scheduler lock for the duration of the block (always True on SQLite)."""
    if engine.dialect.name != "postgresql":
        yield True
        return
    with engine.connect() as connection:  # a dedicated connection: a session-level lock must not ride on the pool
        got = bool(connection.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar())
        try:
            yield got
        finally:
            if got: connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            connection.commit()
