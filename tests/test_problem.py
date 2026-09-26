import pytest

from roster.domain import Block, ClassRef, Subject, Teacher
from roster.problem import Problem, coverage_problems
from tests.fixtures.meridian import meridian_problem


def test_meridian_has_twelve_classes():
    p = meridian_problem()
    assert len(p.classes()) == 12
    assert ClassRef(4, "A") in p.classes()
    assert ClassRef(7, "C") in p.classes()


def test_meridian_has_fourteen_teachers():
    assert len(meridian_problem().teachers) == 14


def test_meridian_demand_is_seven_hundred_and_twenty_periods():
    p = meridian_problem()
    assert sum(p.teacher_load(t) for t in p.teachers) == 720


def test_meridian_covers_every_class_subject_pair():
    assert coverage_problems(meridian_problem()) == []


def test_no_meridian_teacher_is_over_capacity():
    p = meridian_problem()
    loads = {t: p.teacher_load(t) for t in p.teachers}
    assert max(loads.values()) <= 60, loads
    assert min(loads.values()) > 0, loads


def test_block_periods_match_the_curriculum_demand():
    p = meridian_problem()
    for block in p.blocks:
        assert block.periods_per_class == p.demand_for(block.grade)[
            block.subject_code
        ]


def test_every_block_covers_its_whole_grade():
    # One teacher owns a subject for all three classes of a grade.
    p = meridian_problem()
    for block in p.blocks:
        assert block.sections == ("A", "B", "C"), block


def test_one_teacher_owns_each_grade_subject_pair():
    p = meridian_problem()
    for grade in p.grades:
        for code in p.demand_for(grade):
            owners = {
                p.block_for(ClassRef(grade, s), code).teacher_id
                for s in p.sections
            }
            assert len(owners) == 1, (grade, code, owners)


def test_block_for_finds_the_owning_block():
    p = meridian_problem()
    block = p.block_for(ClassRef(4, "A"), "HL")
    assert block is not None
    assert block.grade == 4
    assert block.periods_per_class == 12


def test_block_for_returns_none_for_a_subject_that_grade_does_not_take():
    assert meridian_problem().block_for(ClassRef(4, "A"), "EMS") is None


def test_core_subjects_are_hl_fal_and_math():
    p = meridian_problem()
    assert p.is_core("HL") and p.is_core("FAL") and p.is_core("MATH")
    assert not p.is_core("SS")
    assert not p.is_core("STUDY")


def _minimal_problem(blocks) -> Problem:
    from roster.curriculum import Curriculum, CurriculumEntry, Scenario

    caps = Curriculum((CurriculumEntry(4, "SS", 60),))
    return Problem(
        grades=(4,),
        sections=("A", "B", "C"),
        subjects={"SS": Subject("SS", "Social Sciences", False, False)},
        teachers={
            "t1": Teacher("t1", "Tanya"),
            "t2": Teacher("t2", "Corlie"),
        },
        scenario=Scenario(caps=caps),
        blocks=tuple(blocks),
    )


# Review Focus 5: unassigned and double-assigned triples, including partial overlap.
def test_coverage_reports_an_unassigned_class():
    p = _minimal_problem([Block("t1", 4, "SS", ("A", "B"), 60)])
    problems = coverage_problems(p)
    assert ("unassigned", ClassRef(4, "C"), "SS", 0) in problems


def test_coverage_reports_a_duplicated_class():
    p = _minimal_problem(
        [
            Block("t1", 4, "SS", ("A", "B", "C"), 60),
            Block("t2", 4, "SS", ("A", "B", "C"), 60),
        ]
    )
    problems = coverage_problems(p)
    assert ("duplicate", ClassRef(4, "A"), "SS", 2) in problems
    assert len([x for x in problems if x[0] == "duplicate"]) == 3


def test_coverage_reports_partial_overlap_between_two_blocks():
    # t1 takes A and B, t2 takes B and C: B is covered twice, nothing is missing.
    p = _minimal_problem(
        [
            Block("t1", 4, "SS", ("A", "B"), 60),
            Block("t2", 4, "SS", ("B", "C"), 60),
        ]
    )
    problems = coverage_problems(p)
    assert problems == [("duplicate", ClassRef(4, "B"), "SS", 2)]


def test_teacher_load_sums_every_block():
    p = _minimal_problem(
        [Block("t1", 4, "SS", ("A", "B"), 30), Block("t1", 4, "SS", ("C",), 30)]
    )
    assert p.teacher_load("t1") == 90


def test_unknown_teacher_load_raises():
    with pytest.raises(KeyError):
        meridian_problem().teacher_load("nobody")
