"""In-process per-user sync guard.

At most one sync per user at a time, whatever triggered it — the admin
"Sync Now" button, the scheduler, or the REST trigger endpoint. The server
runs a single worker (see cli.py), so a process-local registry is
authoritative. asyncio is single-threaded and there is no await between
the check and the add, so acquisition is race-free.
"""

from collections.abc import Iterator
from contextlib import contextmanager


class SyncInProgressError(Exception):
    """A sync for this user is already running."""


_in_flight: set[str] = set()


@contextmanager
def sync_slot(user_id: str) -> Iterator[None]:
    """Hold the user's sync slot for the duration of a sync.

    Raises:
        SyncInProgressError: if a sync for this user is already running.
    """
    if user_id in _in_flight:
        raise SyncInProgressError(f"A sync is already running for user {user_id}")
    _in_flight.add(user_id)
    try:
        yield
    finally:
        _in_flight.discard(user_id)


def is_syncing(user_id: str) -> bool:
    """Whether a sync for this user is currently in flight."""
    return user_id in _in_flight


def reset_for_tests() -> None:
    """Clear the registry (test isolation only)."""
    _in_flight.clear()
