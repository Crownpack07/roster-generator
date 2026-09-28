"""Shared fixtures.

The database is mongomock: an in-process reimplementation of MongoDB. It
keeps the whole store and API suite at unit-test speed, at the cost recorded
in spec §9.4 — its index enforcement and error semantics are not Atlas's, so
these tests prove our code issues the right operations, not that Atlas
rejects them identically.
"""

from concurrent.futures import Future

import mongomock
import pytest

from roster.store.indexes import ensure_indexes


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["roster_test"]
    ensure_indexes(database)
    return database


class InlineExecutor:
    """Runs the callable immediately on the calling thread."""

    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001 - mirrors a real pool
            future.set_exception(exc)
        return future

    def shutdown(self, wait: bool = True) -> None:
        return None


class DeferredExecutor:
    """Queues the callable until run_next() is called.

    Lets a test observe the `queued` state, which an inline executor races
    straight past.
    """

    def __init__(self) -> None:
        self.pending: list[tuple[Future, object, tuple, dict]] = []

    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        self.pending.append((future, fn, args, kwargs))
        return future

    def run_next(self) -> None:
        future, fn, args, kwargs = self.pending.pop(0)
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001
            future.set_exception(exc)

    def shutdown(self, wait: bool = True) -> None:
        return None


@pytest.fixture
def inline_executors():
    return InlineExecutor(), InlineExecutor()
