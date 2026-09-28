"""Domain objects to documents and back. No database access here.

Two conventions, fixed once for the whole store:

- A document's `_id` is an ObjectId; a domain object's `id` is `str(_id)`.
- Mappings keyed by (grade, subject_code) flatten to lists of documents,
  because BSON keys must be strings. The flattened shape is exactly the one
  `roster/io.py` already uses, so the stored form and the wire form agree.
"""

from __future__ import annotations

from typing import Any

from roster.curriculum import CurriculumEntry
from roster.domain import Block, Subject, Teacher
from roster.store.records import SchoolRecord, ScenarioRecord, UserRecord


def pairs_to_docs(
    mapping: dict[tuple[int, str], int], value_key: str
) -> list[dict[str, Any]]:
    return [
        {"grade": grade, "subject": code, value_key: value}
        for (grade, code), value in sorted(mapping.items())
    ]


def pairs_from_docs(
    rows: list[dict[str, Any]] | None, value_key: str
) -> dict[tuple[int, str], int]:
    return {
        (row["grade"], row["subject"]): row[value_key] for row in rows or []
    }


def teacher_to_doc(school_id: str, teacher: Teacher) -> dict[str, Any]:
    return {
        "schoolId": school_id,
        "name": teacher.name,
        "blockedSlots": sorted(teacher.blocked_slots),
    }


def teacher_from_doc(doc: dict[str, Any]) -> Teacher:
    return Teacher(
        str(doc["_id"]), doc["name"], frozenset(doc.get("blockedSlots", []))
    )


def subject_to_doc(school_id: str, subject: Subject) -> dict[str, Any]:
    return {
        "schoolId": school_id,
        "code": subject.code,
        "displayName": subject.display_name,
        "isCore": subject.is_core,
        "isOptional": subject.is_optional,
    }


def subject_from_doc(doc: dict[str, Any]) -> Subject:
    return Subject(
        doc["code"], doc["displayName"], doc["isCore"], doc["isOptional"]
    )


def curriculum_entry_to_doc(
    school_id: str, kind: str, entry: CurriculumEntry
) -> dict[str, Any]:
    return {
        "schoolId": school_id,
        "kind": kind,
        "grade": entry.grade,
        "subjectCode": entry.subject_code,
        "periods": entry.periods_per_class,
    }


def curriculum_entry_from_doc(
    doc: dict[str, Any],
) -> tuple[str, CurriculumEntry]:
    return doc["kind"], CurriculumEntry(
        doc["grade"], doc["subjectCode"], doc["periods"]
    )


def block_to_doc(block: Block) -> dict[str, Any]:
    return {
        "teacherId": block.teacher_id,
        "grade": block.grade,
        "subject": block.subject_code,
        "sections": list(block.sections),
        "periodsPerClass": block.periods_per_class,
    }


def block_from_doc(doc: dict[str, Any]) -> Block:
    return Block(
        doc["teacherId"],
        doc["grade"],
        doc["subject"],
        tuple(doc["sections"]),
        doc["periodsPerClass"],
    )


def school_from_doc(doc: dict[str, Any]) -> SchoolRecord:
    return SchoolRecord(
        id=str(doc["_id"]),
        name=doc["name"],
        cycle_days=doc["cycleDays"],
        periods_per_day=doc["periodsPerDay"],
        grades=tuple(doc["grades"]),
        sections=tuple(doc["sections"]),
    )


def user_from_doc(doc: dict[str, Any]) -> UserRecord:
    return UserRecord(
        id=str(doc["_id"]),
        school_id=doc["schoolId"],
        email=doc["email"],
        password_hash=doc["passwordHash"],
    )


def scenario_from_doc(doc: dict[str, Any]) -> ScenarioRecord:
    return ScenarioRecord(
        id=str(doc["_id"]),
        name=doc["name"],
        enabled_optional=frozenset(doc.get("enabledOptional", [])),
        overrides=pairs_from_docs(doc.get("overrides"), "periods"),
        min_doubles=pairs_from_docs(doc.get("minDoubles"), "minimum"),
        blocks=tuple(block_from_doc(b) for b in doc.get("blocks", [])),
    )
