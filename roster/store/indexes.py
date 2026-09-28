"""Index creation. Idempotent — safe to call on every startup.

Every index leads with schoolId, because every query is tenant-scoped and a
compound index is only usable from its prefix.
"""

from __future__ import annotations

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database


def ensure_indexes(db: Database) -> None:
    db["teachers"].create_index([("schoolId", ASCENDING), ("name", ASCENDING)])
    db["subjects"].create_index(
        [("schoolId", ASCENDING), ("code", ASCENDING)], unique=True
    )
    db["curriculum"].create_index(
        [
            ("schoolId", ASCENDING),
            ("kind", ASCENDING),
            ("grade", ASCENDING),
            ("subjectCode", ASCENDING),
        ],
        unique=True,
    )
    db["users"].create_index([("email", ASCENDING)], unique=True)
    db["scenarios"].create_index(
        [("schoolId", ASCENDING), ("name", ASCENDING)]
    )
    db["solutions"].create_index(
        [
            ("schoolId", ASCENDING),
            ("scenarioId", ASCENDING),
            ("createdAt", DESCENDING),
        ]
    )
