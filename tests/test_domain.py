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
