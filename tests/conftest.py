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


from fastapi.testclient import TestClient

from roster.api.app import create_app
from roster.api.security import hash_password
from roster.jobs.runner import SolveRunner
from roster.store.config import Settings
from roster.store.repositories import SchoolRepo, UserRepo

TEST_SETTINGS = Settings(
    mongodb_uri="mongodb://unused",
    session_secret="test-secret",
    solve_time_limit_s=1.0,
    cookie_secure=False,
)


@pytest.fixture
def runner(db):
    """A runner whose executors run inline, so no CP-SAT and no processes."""
    return SolveRunner(
        db,
        solve_fn=lambda snapshot, limit: {
            "status": "feasible",
            "doublesPlaced": 0,
            "doublesCeiling": 0,
            "wallSeconds": 0.0,
            "findings": [],
            "conflict": None,
            "placements": [],
        },
        thread_pool=InlineExecutor(),
        process_pool=InlineExecutor(),
    )


@pytest.fixture
def client(db, runner):
    app = create_app(settings=TEST_SETTINGS, db=db, runner=runner)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def school(db):
    record = SchoolRepo(db).create("Meridian", (4, 5, 6, 7), ("A", "B", "C"))
    UserRepo(db).create(
        record.id, "head@meridian.example", hash_password("pw")
    )
    return record


@pytest.fixture
def signed_in_client(client, school):
    client.post(
        "/auth/login",
        json={"email": "head@meridian.example", "password": "pw"},
    )
    return client
