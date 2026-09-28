"""Shared fixtures.

The database is mongomock: an in-process reimplementation of MongoDB. It
keeps the whole store and API suite at unit-test speed, at the cost recorded
in spec §9.4 — its index enforcement and error semantics are not Atlas's, so
these tests prove our code issues the right operations, not that Atlas
rejects them identically.
"""

import mongomock
import pytest

from roster.store.indexes import ensure_indexes


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["roster_test"]
    ensure_indexes(database)
    return database
