import pytest

from roster.curriculum import CurriculumEntry
from roster.domain import Block, Subject
from roster.store.assemble import AssemblyError, assemble_problem
from roster.store.repositories import (
    CurriculumRepo,
    ScenarioRepo,
    SchoolRepo,
    SubjectRepo,
    TeacherRepo,
)


@pytest.fixture
def seeded(db):
    """A two-grade school with one teacher covering one subject."""
    school = SchoolRepo(db).create("Meridian", (4,), ("A", "B"))
    SubjectRepo(db).create(school.id, Subject("MAT", "Mathematics", True, False))
    SubjectRepo(db).create(school.id, Subject("STUDY", "Study", False, False))
    CurriculumRepo(db).upsert(school.id, "caps", CurriculumEntry(4, "MAT", 8))
    teacher = TeacherRepo(db).create(school.id, "Karin", frozenset({3}))
    scenario = ScenarioRepo(db).create(school.id, "Base")
    ScenarioRepo(db).update(
        school.id,
        scenario.id,
        blocks=(Block(teacher.id, 4, "MAT", ("A", "B"), 8),),
    )
    return school, teacher, scenario


def test_assembly_produces_a_problem_the_core_accepts(db, seeded):
    school, teacher, scenario = seeded
    problem = assemble_problem(db, school.id, scenario.id)

    assert problem.grades == (4,)
    assert problem.sections == ("A", "B")
    assert problem.subjects["MAT"].is_core is True
    assert problem.teachers[teacher.id].blocked_slots == frozenset({3})
    assert problem.scenario.caps.periods(4, "MAT") == 8
    assert problem.blocks == (Block(teacher.id, 4, "MAT", ("A", "B"), 8),)


def test_scenario_choices_reach_the_assembled_problem(db, seeded):
    school, _, scenario = seeded
    CurriculumRepo(db).upsert(school.id, "optional", CurriculumEntry(4, "BIB", 2))
    ScenarioRepo(db).update(
        school.id,
        scenario.id,
        enabled_optional=frozenset({"BIB"}),
        overrides={(4, "MAT"): 7},
        min_doubles={(4, "MAT"): 1},
    )
    problem = assemble_problem(db, school.id, scenario.id)

    assert problem.scenario.enabled_optional == frozenset({"BIB"})
    assert problem.scenario.overrides == {(4, "MAT"): 7}
    assert problem.scenario.min_doubles == {(4, "MAT"): 1}
    assert problem.scenario.optional.periods(4, "BIB") == 2


def test_an_unknown_scenario_is_an_assembly_error(db, seeded):
    school, _, _ = seeded
    with pytest.raises(AssemblyError, match="scenario"):
        assemble_problem(db, school.id, "652000000000000000000000")


def test_a_scenario_from_another_school_is_indistinguishable_from_a_missing_one(
    db, seeded
):
    """Assembly inherits ScenarioRepo's tenant filter rather than enforcing it.

    The isolation itself is tested in test_store_repositories.py; what this
    pins is that assembly surfaces a foreign scenario as "not found" rather
    than leaking it or failing differently.
    """
    _, _, scenario = seeded
    other = SchoolRepo(db).create("Other", (4,), ("A",))
    with pytest.raises(AssemblyError, match="scenario"):
        assemble_problem(db, other.id, scenario.id)


def test_a_block_naming_a_deleted_teacher_is_reported_by_name(db, seeded):
    """Deleting a teacher who still holds blocks is an ordinary sequence.

    Without this check the Problem would carry a block whose teacher_id is
    absent from `teachers`, and the failure would surface much later as a
    KeyError inside the solver.
    """
    school, teacher, scenario = seeded
    TeacherRepo(db).delete(school.id, teacher.id)

    with pytest.raises(AssemblyError, match="teacher"):
        assemble_problem(db, school.id, scenario.id)


def test_a_block_naming_an_unknown_subject_is_reported(db, seeded):
    school, teacher, scenario = seeded
    ScenarioRepo(db).update(
        school.id,
        scenario.id,
        blocks=(Block(teacher.id, 4, "NOPE", ("A",), 2),),
    )
    with pytest.raises(AssemblyError, match="NOPE"):
        assemble_problem(db, school.id, scenario.id)
