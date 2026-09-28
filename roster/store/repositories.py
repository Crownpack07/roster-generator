"""One repository per collection.

**Every method takes school_id as its first positional parameter.** There is
no overload that omits it and no module-level default, so a query that
forgets its tenant scope does not type-check rather than leaking another
school's data past review.

`UserRepo.by_email` is the single deliberate exception; see its docstring.
"""

from __future__ import annotations

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
    """An unparseable id means 'not found', never a 500."""
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
            for d in self._c.find({"schoolId": school_id}).sort("name", 1)
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
