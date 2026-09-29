"""One repository per collection.

**Every method takes school_id as its first positional parameter.** There is
no overload that omits it and no module-level default, so a query that
forgets its tenant scope does not type-check rather than leaking another
school's data past review.

`UserRepo.by_email` is the single deliberate exception; see its docstring.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from roster.curriculum import CurriculumEntry
from roster.domain import DAYS, PERIODS_PER_DAY, Block, Subject, Teacher
from roster.store.codecs import (
    block_to_doc,
    curriculum_entry_from_doc,
    curriculum_entry_to_doc,
    pairs_to_docs,
    scenario_from_doc,
    school_from_doc,
    subject_from_doc,
    subject_to_doc,
    teacher_from_doc,
    teacher_to_doc,
    user_from_doc,
)
from roster.store.records import SchoolRecord, ScenarioRecord, UserRecord


class ValidationError(Exception):
    """A value the store refuses to write."""


def _oid(value: str) -> ObjectId | None:
    """An unparseable id means 'not found', never a 500.

    Guard falsy input explicitly: ObjectId(None) raises neither InvalidId nor
    TypeError, it silently mints a fresh random id, which would make a
    missing id look up as "not found" only by the coincidence of matching no
    document.
    """
    if not value:
        return None
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


class SchoolRepo:
    def __init__(self, db: Database) -> None:
        self._c = db["schools"]

    def create(
        self,
        name: str,
        grades: tuple[int, ...],
        sections: tuple[str, ...],
        *,
        cycle_days: int = DAYS,
        periods_per_day: int = PERIODS_PER_DAY,
    ) -> SchoolRecord:
        # roster/domain.py hardcodes the cycle. Storing anything else would
        # not fail loudly; it would produce a confidently wrong timetable.
        if cycle_days != DAYS:
            raise ValidationError(
                f"cycleDays must be {DAYS}; this solver models a "
                f"{DAYS}-day cycle only"
            )
        if periods_per_day != PERIODS_PER_DAY:
            raise ValidationError(
                f"periodsPerDay must be {PERIODS_PER_DAY}; this solver models "
                f"{PERIODS_PER_DAY} periods a day only"
            )
        if not grades or not sections:
            raise ValidationError("a school needs at least one grade and one section")
        doc = {
            "name": name,
            "cycleDays": cycle_days,
            "periodsPerDay": periods_per_day,
            "grades": list(grades),
            "sections": list(sections),
        }
        doc["_id"] = self._c.insert_one(doc).inserted_id
        return school_from_doc(doc)

    def get(self, school_id: str) -> SchoolRecord | None:
        oid = _oid(school_id)
        if oid is None:
            return None
        doc = self._c.find_one({"_id": oid})
        return school_from_doc(doc) if doc else None

    def update(self, school_id: str, *, name: str | None = None) -> SchoolRecord | None:
        oid = _oid(school_id)
        if oid is None:
            return None
        if name is not None:
            self._c.update_one({"_id": oid}, {"$set": {"name": name}})
        return self.get(school_id)


class UserRepo:
    def __init__(self, db: Database) -> None:
        self._c = db["users"]

    def create(
        self, school_id: str, email: str, password_hash: str
    ) -> UserRecord:
        # See SubjectRepo.create: checked here, not left to the index.
        if self.by_email(email) is not None:
            raise DuplicateKeyError(f"{email} already has an account")
        doc = {
            "schoolId": school_id,
            "email": email,
            "passwordHash": password_hash,
        }
        doc["_id"] = self._c.insert_one(doc).inserted_id
        return user_from_doc(doc)

    def by_email(self, email: str) -> UserRecord | None:
        """The one method with no tenant filter, and necessarily so.

        Login resolves the school FROM the address, so it cannot already know
        which school to scope to. An email therefore identifies exactly one
        school, which the unique index on `email` enforces.
        """
        doc = self._c.find_one({"email": email})
        return user_from_doc(doc) if doc else None

    def get(self, school_id: str, user_id: str) -> UserRecord | None:
        oid = _oid(user_id)
        if oid is None:
            return None
        doc = self._c.find_one({"_id": oid, "schoolId": school_id})
        return user_from_doc(doc) if doc else None


class TeacherRepo:
    def __init__(self, db: Database) -> None:
        self._c = db["teachers"]

    def create(
        self, school_id: str, name: str, blocked_slots: frozenset[int]
    ) -> Teacher:
        doc = teacher_to_doc(school_id, Teacher("", name, blocked_slots))
        doc["_id"] = self._c.insert_one(doc).inserted_id
        return teacher_from_doc(doc)

    def list(self, school_id: str) -> list[Teacher]:
        return [
            teacher_from_doc(d)
            for d in self._c.find({"schoolId": school_id}).sort(
                [("name", 1), ("_id", 1)]
            )
        ]

    def get(self, school_id: str, teacher_id: str) -> Teacher | None:
        oid = _oid(teacher_id)
        if oid is None:
            return None
        doc = self._c.find_one({"_id": oid, "schoolId": school_id})
        return teacher_from_doc(doc) if doc else None

    def update(
        self,
        school_id: str,
        teacher_id: str,
        *,
        name: str | None = None,
        blocked_slots: frozenset[int] | None = None,
    ) -> Teacher | None:
        oid = _oid(teacher_id)
        if oid is None:
            return None
        changes: dict[str, Any] = {}
        if name is not None:
            changes["name"] = name
        if blocked_slots is not None:
            changes["blockedSlots"] = sorted(blocked_slots)
        if changes:
            result = self._c.update_one(
                {"_id": oid, "schoolId": school_id}, {"$set": changes}
            )
            if result.matched_count == 0:
                return None
        return self.get(school_id, teacher_id)

    def delete(self, school_id: str, teacher_id: str) -> bool:
        oid = _oid(teacher_id)
        if oid is None:
            return False
        return (
            self._c.delete_one(
                {"_id": oid, "schoolId": school_id}
            ).deleted_count
            == 1
        )


class SubjectRepo:
    def __init__(self, db: Database) -> None:
        self._c = db["subjects"]

    def create(self, school_id: str, subject: Subject) -> Subject:
        # Checked here rather than left to the unique index. mongomock's index
        # enforcement is not Atlas's, so a test relying on the index would be
        # a coin flip on a library detail. Against Atlas the index remains the
        # backstop for a genuine race between two writers.
        if self.get(school_id, subject.code) is not None:
            raise DuplicateKeyError(
                f"subject {subject.code} already exists in school {school_id}"
            )
        self._c.insert_one(subject_to_doc(school_id, subject))
        return subject

    def list(self, school_id: str) -> list[Subject]:
        return [
            subject_from_doc(d)
            for d in self._c.find({"schoolId": school_id}).sort("code", 1)
        ]

    def get(self, school_id: str, code: str) -> Subject | None:
        doc = self._c.find_one({"schoolId": school_id, "code": code})
        return subject_from_doc(doc) if doc else None

    def update(
        self,
        school_id: str,
        code: str,
        *,
        display_name: str | None = None,
        is_core: bool | None = None,
        is_optional: bool | None = None,
    ) -> Subject | None:
        changes: dict[str, Any] = {}
        if display_name is not None:
            changes["displayName"] = display_name
        if is_core is not None:
            changes["isCore"] = is_core
        if is_optional is not None:
            changes["isOptional"] = is_optional
        if changes:
            result = self._c.update_one(
                {"schoolId": school_id, "code": code}, {"$set": changes}
            )
            if result.matched_count == 0:
                return None
        return self.get(school_id, code)

    def delete(self, school_id: str, code: str) -> bool:
        return (
            self._c.delete_one(
                {"schoolId": school_id, "code": code}
            ).deleted_count
            == 1
        )


class CurriculumRepo:
    def __init__(self, db: Database) -> None:
        self._c = db["curriculum"]

    def upsert(
        self, school_id: str, kind: str, entry: CurriculumEntry
    ) -> CurriculumEntry:
        self._c.update_one(
            {
                "schoolId": school_id,
                "kind": kind,
                "grade": entry.grade,
                "subjectCode": entry.subject_code,
            },
            {"$set": curriculum_entry_to_doc(school_id, kind, entry)},
            upsert=True,
        )
        return entry

    def list(self, school_id: str, kind: str) -> list[CurriculumEntry]:
        rows = self._c.find({"schoolId": school_id, "kind": kind}).sort(
            [("grade", 1), ("subjectCode", 1)]
        )
        return [curriculum_entry_from_doc(d)[1] for d in rows]

    def delete(
        self, school_id: str, kind: str, grade: int, subject_code: str
    ) -> bool:
        return (
            self._c.delete_one(
                {
                    "schoolId": school_id,
                    "kind": kind,
                    "grade": grade,
                    "subjectCode": subject_code,
                }
            ).deleted_count
            == 1
        )


class ScenarioRepo:
    def __init__(self, db: Database) -> None:
        self._c = db["scenarios"]

    def create(self, school_id: str, name: str) -> ScenarioRecord:
        doc: dict[str, Any] = {
            "schoolId": school_id,
            "name": name,
            "enabledOptional": [],
            "overrides": [],
            "minDoubles": [],
            "blocks": [],
        }
        doc["_id"] = self._c.insert_one(doc).inserted_id
        return scenario_from_doc(doc)

    def list(self, school_id: str) -> list[ScenarioRecord]:
        return [
            scenario_from_doc(d)
            for d in self._c.find({"schoolId": school_id}).sort("name", 1)
        ]

    def get(self, school_id: str, scenario_id: str) -> ScenarioRecord | None:
        oid = _oid(scenario_id)
        if oid is None:
            return None
        doc = self._c.find_one({"_id": oid, "schoolId": school_id})
        return scenario_from_doc(doc) if doc else None

    def update(
        self,
        school_id: str,
        scenario_id: str,
        *,
        name: str | None = None,
        enabled_optional: frozenset[str] | None = None,
        overrides: dict[tuple[int, str], int] | None = None,
        min_doubles: dict[tuple[int, str], int] | None = None,
        blocks: tuple[Block, ...] | None = None,
    ) -> ScenarioRecord | None:
        oid = _oid(scenario_id)
        if oid is None:
            return None
        changes: dict[str, Any] = {}
        if name is not None:
            changes["name"] = name
        if enabled_optional is not None:
            changes["enabledOptional"] = sorted(enabled_optional)
        if overrides is not None:
            changes["overrides"] = pairs_to_docs(overrides, "periods")
        if min_doubles is not None:
            changes["minDoubles"] = pairs_to_docs(min_doubles, "minimum")
        if blocks is not None:
            changes["blocks"] = [block_to_doc(b) for b in blocks]
        if changes:
            result = self._c.update_one(
                {"_id": oid, "schoolId": school_id}, {"$set": changes}
            )
            if result.matched_count == 0:
                return None
        return self.get(school_id, scenario_id)

    def delete(self, school_id: str, scenario_id: str) -> bool:
        oid = _oid(scenario_id)
        if oid is None:
            return False
        return (
            self._c.delete_one(
                {"_id": oid, "schoolId": school_id}
            ).deleted_count
            == 1
        )


class SolutionRepo:
    """The solutions collection, which doubles as the job record.

    A solution document is created the moment a solve is requested and fills
    in as the job progresses, so there is no second collection to keep
    consistent with it.

    `jobStatus` and `solveStatus` are separate fields and are never merged.
    `solveStatus` stays None unless `jobStatus` is "done".
    """

    def __init__(self, db: Database) -> None:
        self._c = db["solutions"]

    @staticmethod
    def _public(doc: dict[str, Any]) -> dict[str, Any]:
        out = dict(doc)
        out["id"] = str(out.pop("_id"))
        return out

    def create_queued(
        self,
        school_id: str,
        scenario_id: str,
        snapshot: dict[str, Any],
        time_limit_s: float,
        solver_version: str = "",
    ) -> str:
        doc: dict[str, Any] = {
            "schoolId": school_id,
            "scenarioId": scenario_id,
            "jobStatus": "queued",
            "solveStatus": None,
            "inputSnapshot": snapshot,
            "timeLimitS": time_limit_s,
            "solverVersion": solver_version,
            "placements": [],
            "stats": None,
            "findings": [],
            "conflict": None,
            "error": None,
            "createdAt": datetime.now(timezone.utc),
            "startedAt": None,
            "finishedAt": None,
        }
        return str(self._c.insert_one(doc).inserted_id)

    def get(self, school_id: str, solution_id: str) -> dict[str, Any] | None:
        oid = _oid(solution_id)
        if oid is None:
            return None
        doc = self._c.find_one({"_id": oid, "schoolId": school_id})
        return self._public(doc) if doc else None

    def list_for_scenario(
        self, school_id: str, scenario_id: str
    ) -> list[dict[str, Any]]:
        rows = self._c.find(
            {"schoolId": school_id, "scenarioId": scenario_id},
            {"inputSnapshot": 0, "placements": 0},
        ).sort("createdAt", -1)
        return [self._public(d) for d in rows]

    def mark_running(self, school_id: str, solution_id: str) -> bool:
        """Only queued jobs may start.

        This filter is what makes cancellation race-free: a job cancelled
        between submission and execution simply never begins.
        """
        oid = _oid(solution_id)
        if oid is None:
            return False
        result = self._c.update_one(
            {"_id": oid, "schoolId": school_id, "jobStatus": "queued"},
            {
                "$set": {
                    "jobStatus": "running",
                    "startedAt": datetime.now(timezone.utc),
                }
            },
        )
        return result.matched_count == 1

    def mark_done(
        self, school_id: str, solution_id: str, payload: dict[str, Any]
    ) -> bool:
        """Only a running job may finish.

        Matching on `jobStatus: "running"` stops a terminal document from
        being resurrected: if a startup sweep already marked this job
        `failed` while a stray solve was still in flight, that solve's
        result must be dropped, not allowed to overwrite the failure with
        contradictory fields (e.g. `done` with a leftover restart error).
        """
        oid = _oid(solution_id)
        if oid is None:
            return False
        result = self._c.update_one(
            {"_id": oid, "schoolId": school_id, "jobStatus": "running"},
            {
                "$set": {
                    "jobStatus": "done",
                    "solveStatus": payload["status"],
                    "placements": payload.get("placements", []),
                    "findings": payload.get("findings", []),
                    "conflict": payload.get("conflict"),
                    "stats": {
                        "doublesPlaced": payload.get("doublesPlaced", 0),
                        "doublesCeiling": payload.get("doublesCeiling", 0),
                        "wallSeconds": payload.get("wallSeconds", 0.0),
                    },
                    "finishedAt": datetime.now(timezone.utc),
                }
            },
        )
        return result.matched_count == 1

    def mark_failed(
        self, school_id: str, solution_id: str, error: str
    ) -> bool:
        """A crashed job. `solveStatus` stays None — never "unknown".

        Matching on `jobStatus: {"$in": ["queued", "running"]}` is the same
        anti-resurrection guard as `mark_done`'s: a job that is already
        terminal (done, failed, or cancelled) must not be overwritten.
        """
        oid = _oid(solution_id)
        if oid is None:
            return False
        result = self._c.update_one(
            {
                "_id": oid,
                "schoolId": school_id,
                "jobStatus": {"$in": ["queued", "running"]},
            },
            {
                "$set": {
                    "jobStatus": "failed",
                    "solveStatus": None,
                    "error": error,
                    "finishedAt": datetime.now(timezone.utc),
                }
            },
        )
        return result.matched_count == 1

    def cancel_if_queued(self, school_id: str, solution_id: str) -> bool:
        oid = _oid(solution_id)
        if oid is None:
            return False
        result = self._c.update_one(
            {"_id": oid, "schoolId": school_id, "jobStatus": "queued"},
            {
                "$set": {
                    "jobStatus": "cancelled",
                    "finishedAt": datetime.now(timezone.utc),
                }
            },
        )
        return result.matched_count == 1

    def sweep_orphans(self) -> int:
        """Fail every job left behind by a previous process lifetime.

        Runs at startup across all tenants — the one method here with no
        school filter, because a restart orphans every school's jobs alike.
        The process pool dies with the container, so anything still queued or
        running has no one left to finish it.

        This assumes a SINGLE application process. Running more than one —
        for example `uvicorn --workers N` with N > 1, or a rolling deploy
        that briefly overlaps an old and a new process — makes this method
        unsafe: a second process's startup sweep will fail a first process's
        still-live jobs out from under it, because it cannot distinguish
        "orphaned by a dead process" from "in progress in a live one".

        `mark_done` and `mark_failed` both filter on the job status they
        expect, so a wrongly-swept job cannot be resurrected into a
        contradictory document — the in-flight solve's result is silently
        dropped and the job is left `failed`, and a user just re-runs it.
        That is the accepted degradation for this deployment shape. Fixing
        it properly (a lease or heartbeat per job) is out of scope: the spec
        explicitly descopes heartbeats for a one-container deployment. The
        mitigation here is deployment configuration — run exactly one
        process — not code.
        """
        result = self._c.update_many(
            {"jobStatus": {"$in": ["queued", "running"]}},
            {
                "$set": {
                    "jobStatus": "failed",
                    "solveStatus": None,
                    "error": "server restarted during solve",
                    "finishedAt": datetime.now(timezone.utc),
                }
            },
        )
        return result.modified_count
