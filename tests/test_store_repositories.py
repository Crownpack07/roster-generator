import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from roster.curriculum import CurriculumEntry
from roster.domain import Subject, Teacher
from roster.store.repositories import (
    CurriculumRepo,
    ScenarioRepo,
    SchoolRepo,
    SubjectRepo,
    TeacherRepo,
    UserRepo,
    ValidationError,
)


@pytest.fixture
def school(db):
    return SchoolRepo(db).create("Meridian", (4, 5, 6, 7), ("A", "B", "C"))


def test_a_school_defaults_to_the_six_by_ten_cycle(db):
    record = SchoolRepo(db).create("Meridian", (4,), ("A",))
    assert record.cycle_days == 6
    assert record.periods_per_day == 10


def test_a_school_with_a_different_cycle_is_refused(db):
    """roster/domain.py hardcodes DAYS = 6 and PERIODS_PER_DAY = 10.

    A school stored with five days would not fail — it would produce a
    confidently wrong timetable, which P1 §14 names as the real risk.
    """
    with pytest.raises(ValidationError, match="cycleDays"):
        SchoolRepo(db).create("Short week", (4,), ("A",), cycle_days=5)
    with pytest.raises(ValidationError, match="periodsPerDay"):
        SchoolRepo(db).create("Long day", (4,), ("A",), periods_per_day=12)


def test_a_teacher_is_created_read_updated_and_deleted(db, school):
    repo = TeacherRepo(db)
    teacher = repo.create(school.id, "Karin", frozenset({3}))

    assert repo.get(school.id, teacher.id) == teacher
    assert repo.list(school.id) == [teacher]

    updated = repo.update(school.id, teacher.id, blocked_slots=frozenset({7, 8}))
    assert updated is not None
    assert updated.blocked_slots == frozenset({7, 8})
    assert updated.name == "Karin"

    assert repo.delete(school.id, teacher.id) is True
    assert repo.get(school.id, teacher.id) is None
    assert repo.delete(school.id, teacher.id) is False


def test_a_teacher_belonging_to_another_school_is_invisible(db, school):
    """The Review Focus case, checked at the repository rather than the route.

    get() returning None is what lets the route answer 404 without having to
    know whether the document exists at all.
    """
    other = SchoolRepo(db).create("Other", (4,), ("A",))
    repo = TeacherRepo(db)
    teacher = repo.create(other.id, "Shane", frozenset())

    assert repo.get(school.id, teacher.id) is None
    assert repo.list(school.id) == []
    assert repo.update(school.id, teacher.id, name="Renamed") is None
    assert repo.delete(school.id, teacher.id) is False
    # ...and the real owner still has it, unchanged.
    assert repo.get(other.id, teacher.id) == teacher


def test_a_malformed_id_is_not_found_rather_than_a_crash(db, school):
    """bson raises InvalidId for a non-hex string; a 500 would be wrong."""
    assert TeacherRepo(db).get(school.id, "not-an-object-id") is None
    assert TeacherRepo(db).delete(school.id, "not-an-object-id") is False


def test_a_none_id_is_not_found_rather_than_a_random_document(db, school):
    """ObjectId(None) raises neither InvalidId nor TypeError — it mints a
    fresh random id. Without an explicit guard, "not found" would hold only
    by the coincidence of that random id matching nothing.
    """
    assert TeacherRepo(db).get(school.id, None) is None


def test_a_subject_is_keyed_by_its_code_within_a_school(db, school):
    repo = SubjectRepo(db)
    subject = Subject("MAT", "Mathematics", True, False)
    repo.create(school.id, subject)

    assert repo.get(school.id, "MAT") == subject
    assert repo.get(school.id, "ENG") is None

    other = SchoolRepo(db).create("Other", (4,), ("A",))
    assert repo.get(other.id, "MAT") is None
    # The same code in a different school is a different subject, not a clash.
    repo.create(other.id, Subject("MAT", "Wiskunde", True, False))
    assert repo.get(other.id, "MAT").display_name == "Wiskunde"


def test_a_duplicate_subject_code_within_a_school_is_refused(db, school):
    repo = SubjectRepo(db)
    repo.create(school.id, Subject("MAT", "Mathematics", True, False))

    with pytest.raises(DuplicateKeyError, match="already exists in school"):
        repo.create(school.id, Subject("MAT", "Maths again", True, False))


def test_a_duplicate_email_is_refused_even_in_a_different_school(db, school):
    """An email identifies exactly one school, so it cannot be reused."""
    other = SchoolRepo(db).create("Other", (4,), ("A",))
    UserRepo(db).create(school.id, "head@meridian.example", "hash")

    with pytest.raises(DuplicateKeyError, match="already has an account"):
        UserRepo(db).create(other.id, "head@meridian.example", "hash")


def test_curriculum_entries_are_separated_by_kind(db, school):
    repo = CurriculumRepo(db)
    repo.upsert(school.id, "caps", CurriculumEntry(4, "MAT", 8))
    repo.upsert(school.id, "optional", CurriculumEntry(4, "BIB", 2))

    assert repo.list(school.id, "caps") == [CurriculumEntry(4, "MAT", 8)]
    assert repo.list(school.id, "optional") == [CurriculumEntry(4, "BIB", 2)]


def test_upserting_the_same_grade_and_subject_replaces_the_period_count(
    db, school
):
    repo = CurriculumRepo(db)
    repo.upsert(school.id, "caps", CurriculumEntry(4, "MAT", 8))
    repo.upsert(school.id, "caps", CurriculumEntry(4, "MAT", 9))

    assert repo.list(school.id, "caps") == [CurriculumEntry(4, "MAT", 9)]


def test_a_scenario_round_trips_its_choices_and_blocks(db, school):
    repo = ScenarioRepo(db)
    created = repo.create(school.id, "With Sepedi")

    updated = repo.update(
        school.id,
        created.id,
        enabled_optional=frozenset({"BIB"}),
        overrides={(4, "MAT"): 7},
        min_doubles={(4, "ENG"): 2},
    )
    assert updated is not None
    assert updated.overrides == {(4, "MAT"): 7}
    assert updated.min_doubles == {(4, "ENG"): 2}

    # Read back from the database, not from the returned object.
    assert repo.get(school.id, created.id) == updated


def test_cross_tenant_isolation_sweep(db, school):
    """One sweep across every method not already covered by its own
    cross-tenant test, so a dropped schoolId filter fails a test instead of
    surfacing only in review.

    Written as one compact test rather than nine near-identical ones: each
    sub-block seeds a record under `school`, then proves `other` cannot get,
    list, update, or delete it, and that `school` still can, unchanged.
    Covers: UserRepo.get, SubjectRepo.list/update/delete,
    CurriculumRepo.upsert/list/delete, ScenarioRepo.list/delete.
    """
    other = SchoolRepo(db).create("Other", (4,), ("A",))

    # UserRepo.get
    users = UserRepo(db)
    user = users.create(school.id, "sweep@meridian.example", "hash")
    assert users.get(other.id, user.id) is None
    assert users.get(school.id, user.id) == user

    # SubjectRepo.list / .update / .delete
    subjects = SubjectRepo(db)
    subject = subjects.create(school.id, Subject("PHY", "Physics", True, False))
    assert subjects.list(other.id) == []
    assert subjects.update(other.id, "PHY", display_name="Hijacked") is None
    assert subjects.delete(other.id, "PHY") is False
    assert subjects.get(school.id, "PHY") == subject

    # CurriculumRepo.upsert / .list / .delete
    curriculum = CurriculumRepo(db)
    entry = CurriculumEntry(4, "PHY", 6)
    curriculum.upsert(school.id, "caps", entry)
    assert curriculum.list(other.id, "caps") == []
    assert curriculum.delete(other.id, "caps", 4, "PHY") is False
    # upsert() from `other` must scope its match filter by schoolId too: it
    # has to create a separate document rather than silently overwrite
    # `school`'s row for the same (kind, grade, subjectCode).
    curriculum.upsert(other.id, "caps", CurriculumEntry(4, "PHY", 99))
    assert curriculum.list(school.id, "caps") == [entry]

    # ScenarioRepo.list / .delete
    scenarios = ScenarioRepo(db)
    scenario = scenarios.create(school.id, "Sweep scenario")
    assert scenarios.list(other.id) == []
    assert scenarios.delete(other.id, scenario.id) is False
    assert scenarios.get(school.id, scenario.id) == scenario


def test_a_user_is_found_by_email_across_schools(db, school):
    """by_email is the one method with no tenant filter, by necessity."""
    repo = UserRepo(db)
    user = repo.create(school.id, "head@meridian.example", "hash")

    found = repo.by_email("head@meridian.example")
    assert found is not None
    assert found.id == user.id
    assert found.school_id == school.id
    assert repo.by_email("nobody@example.com") is None
