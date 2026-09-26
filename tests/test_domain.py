import pytest

from roster.domain import (
    DAYS,
    PERIODS_PER_DAY,
    SLOT_COUNT,
    adjacent_pairs_of_day,
    all_adjacent_pairs,
    day_of,
    is_adjacent,
    period_of,
    slots_of_day,
)


def test_cycle_shape():
    assert DAYS == 6
    assert PERIODS_PER_DAY == 10
    assert SLOT_COUNT == 60


def test_slot_decomposes_into_day_and_period():
    assert (day_of(0), period_of(0)) == (0, 0)
    assert (day_of(9), period_of(9)) == (0, 9)
    assert (day_of(10), period_of(10)) == (1, 0)
    assert (day_of(59), period_of(59)) == (5, 9)


def test_slots_of_day_returns_ten_contiguous_slots():
    assert slots_of_day(0) == list(range(0, 10))
    assert slots_of_day(5) == list(range(50, 60))


def test_each_day_has_nine_adjacent_pairs():
    pairs = adjacent_pairs_of_day(0)
    assert len(pairs) == 9
    assert pairs[0] == (0, 1)
    assert pairs[-1] == (8, 9)


def test_all_adjacent_pairs_covers_every_day():
    assert len(all_adjacent_pairs()) == DAYS * 9


def test_day_boundary_is_not_adjacent():
    # Slot 9 is day 0 period 10; slot 10 is day 1 period 1.
    # Numerically consecutive, but a double may never span them.
    assert is_adjacent(8, 9) is True
    assert is_adjacent(9, 10) is False
    assert is_adjacent(19, 20) is False
    assert (9, 10) not in all_adjacent_pairs()


def test_adjacency_is_symmetric_and_rejects_gaps():
    assert is_adjacent(4, 3) is True
    assert is_adjacent(3, 5) is False
    assert is_adjacent(3, 3) is False


@pytest.mark.parametrize("bad", [-1, 60, 999])
def test_out_of_range_slot_rejected(bad):
    with pytest.raises(ValueError):
        day_of(bad)


from roster.domain import Block, ClassRef, Placement, Schedule, Subject, Teacher


def test_class_ref_prints_as_grade_and_section():
    assert str(ClassRef(4, "A")) == "4A"
    assert str(ClassRef(7, "C")) == "7C"


def test_block_total_is_periods_times_classes():
    block = Block("t1", 4, "HL", ("A", "B", "C"), 12)
    assert block.total_periods == 36
    assert block.class_refs() == (ClassRef(4, "A"), ClassRef(4, "B"), ClassRef(4, "C"))


def test_block_may_cover_fewer_than_all_sections():
    # Filler duty split per class, or a subject shared between two teachers.
    block = Block("t2", 5, "STUDY", ("B",), 1)
    assert block.total_periods == 1
    assert block.class_refs() == (ClassRef(5, "B"),)


def test_block_rejects_empty_sections():
    with pytest.raises(ValueError):
        Block("t1", 4, "HL", (), 12)


def test_block_rejects_duplicate_sections():
    with pytest.raises(ValueError):
        Block("t1", 4, "HL", ("A", "A"), 12)


def test_teacher_blocked_slots_are_a_frozenset():
    teacher = Teacher("t1", "Petra", frozenset({10, 11}))
    assert 10 in teacher.blocked_slots
    assert 12 not in teacher.blocked_slots


def test_schedule_maps_slots_to_subjects_per_class():
    c = ClassRef(4, "A")
    schedule = Schedule(
        (
            Placement(c, "HL", 0),
            Placement(c, "HL", 1),
            Placement(c, "MATH", 2),
        )
    )
    assert schedule.for_class(c) == {0: "HL", 1: "HL", 2: "MATH"}
    assert schedule.slots_of(c, "HL") == [0, 1]
    assert schedule.slots_of(c, "SS") == []


def test_schedule_slots_are_returned_sorted():
    c = ClassRef(6, "B")
    schedule = Schedule((Placement(c, "SS", 41), Placement(c, "SS", 7)))
    assert schedule.slots_of(c, "SS") == [7, 41]


def test_subject_flags():
    core = Subject("MATH", "Mathematics", is_core=True, is_optional=False)
    optional = Subject("BIB", "Bible Education", is_core=False, is_optional=True)
    assert core.is_core and not core.is_optional
    assert optional.is_optional and not optional.is_core
