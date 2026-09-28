from bson import ObjectId

from roster.curriculum import CurriculumEntry
from roster.domain import Block, Subject, Teacher
from roster.store.codecs import (
    block_from_doc,
    block_to_doc,
    curriculum_entry_from_doc,
    curriculum_entry_to_doc,
    pairs_from_docs,
    pairs_to_docs,
    scenario_from_doc,
    school_from_doc,
    subject_from_doc,
    subject_to_doc,
    teacher_from_doc,
    teacher_to_doc,
    user_from_doc,
)


def test_a_teacher_round_trips_with_its_blocked_slots():
    oid = ObjectId()
    teacher = Teacher(str(oid), "Karin", frozenset({3, 4}))
    doc = teacher_to_doc("school-1", teacher)
    doc["_id"] = oid

    assert doc["schoolId"] == "school-1"
    assert doc["blockedSlots"] == [3, 4]  # a list; BSON has no set
    assert teacher_from_doc(doc) == teacher


def test_a_teacher_with_no_blocked_slots_round_trips_to_an_empty_frozenset():
    oid = ObjectId()
    doc = {"_id": oid, "schoolId": "s", "name": "Shane", "blockedSlots": []}
    assert teacher_from_doc(doc) == Teacher(str(oid), "Shane", frozenset())


def test_a_subject_round_trips():
    subject = Subject("MAT", "Mathematics", True, False)
    doc = subject_to_doc("school-1", subject)
    assert doc["code"] == "MAT"
    assert subject_from_doc(doc) == subject


def test_a_curriculum_entry_carries_its_kind():
    entry = CurriculumEntry(4, "MAT", 8)
    doc = curriculum_entry_to_doc("school-1", "caps", entry)
    assert doc["kind"] == "caps"
    assert curriculum_entry_from_doc(doc) == ("caps", entry)


def test_tuple_keyed_pairs_flatten_and_restore():
    """Scenario.overrides is keyed by (grade, code). BSON cannot store that.

    Phase 1's Task 12 review found this round trip was only ever exercised
    with an EMPTY mapping, which passes whatever the implementation does.
    """
    mapping = {(4, "MAT"): 7, (7, "ENG"): 9}
    rows = pairs_to_docs(mapping, "periods")
    assert rows == [
        {"grade": 4, "subject": "MAT", "periods": 7},
        {"grade": 7, "subject": "ENG", "periods": 9},
    ]
    assert pairs_from_docs(rows, "periods") == mapping


def test_a_block_round_trips():
    block = Block("t1", 4, "MAT", ("A", "B"), 8)
    assert block_from_doc(block_to_doc(block)) == block


def test_a_school_document_becomes_a_record():
    oid = ObjectId()
    record = school_from_doc(
        {
            "_id": oid,
            "name": "Meridian",
            "cycleDays": 6,
            "periodsPerDay": 10,
            "grades": [4, 5, 6, 7],
            "sections": ["A", "B", "C"],
        }
    )
    assert record.id == str(oid)
    assert record.grades == (4, 5, 6, 7)
    assert record.sections == ("A", "B", "C")


def test_a_scenario_document_becomes_a_record_with_populated_overrides():
    """The Review Focus case: overrides AND min_doubles both non-empty."""
    oid = ObjectId()
    record = scenario_from_doc(
        {
            "_id": oid,
            "schoolId": "s",
            "name": "With Sepedi",
            "enabledOptional": ["BIB", "SPT"],
            "overrides": [{"grade": 4, "subject": "MAT", "periods": 7}],
            "minDoubles": [{"grade": 4, "subject": "ENG", "minimum": 2}],
            "blocks": [
                {
                    "teacherId": "t1",
                    "grade": 4,
                    "subject": "MAT",
                    "sections": ["A", "B", "C"],
                    "periodsPerClass": 8,
                }
            ],
        }
    )
    assert record.id == str(oid)
    assert record.enabled_optional == frozenset({"BIB", "SPT"})
    assert record.overrides == {(4, "MAT"): 7}
    assert record.min_doubles == {(4, "ENG"): 2}
    assert record.blocks == (Block("t1", 4, "MAT", ("A", "B", "C"), 8),)


def test_a_scenario_document_with_no_optional_fields_still_decodes():
    """Documents written by an earlier version may omit optional keys."""
    record = scenario_from_doc(
        {"_id": ObjectId(), "schoolId": "s", "name": "Bare"}
    )
    assert record.enabled_optional == frozenset()
    assert record.overrides == {}
    assert record.min_doubles == {}
    assert record.blocks == ()


def test_a_user_document_becomes_a_record():
    oid = ObjectId()
    record = user_from_doc(
        {
            "_id": oid,
            "schoolId": "school-1",
            "email": "head@meridian.example",
            "passwordHash": "not-a-real-hash",
        }
    )
    assert record.id == str(oid)
    assert record.school_id == "school-1"
    assert record.email == "head@meridian.example"
    assert record.password_hash == "not-a-real-hash"
