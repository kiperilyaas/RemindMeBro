"""
One sync at a time.

SQLite lets a single connection write at a time. The live UniLearn poll (live_sync, every 30 s) and a Sync the
student presses both import posts and run the AI on them, which can keep a write transaction open for many
seconds: when they overlapped, the second one failed with "database is locked". Every sync takes this lock:
a Sync pressed by a user waits for the poll round to finish, and the poll skips its round while a Sync runs.
RLock: run_sync_pipeline calls the UniSIS and UniLearn syncs from the same thread.
"""
from __future__ import annotations

import functools
import threading
from contextlib import contextmanager
from typing import Callable, Iterator, TypeVar

SYNC_LOCK = threading.RLock()
F = TypeVar("F", bound=Callable)


def exclusive(fn: F) -> F:
    """Decorator: the function runs while holding the sync lock (waits for it)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with SYNC_LOCK:
            return fn(*args, **kwargs)
    return wrapper  # type: ignore[return-value]


@contextmanager
def try_exclusive() -> Iterator[bool]:
    """For background work: yields False (and does nothing) when a sync is already running."""
    got = SYNC_LOCK.acquire(blocking=False)
    try:
        yield got
    finally:
        if got:
            SYNC_LOCK.release()
