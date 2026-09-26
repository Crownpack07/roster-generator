"""Entities and slot arithmetic. Pure data and pure functions."""

from __future__ import annotations

from dataclasses import dataclass

DAYS = 6
PERIODS_PER_DAY = 10
SLOT_COUNT = DAYS * PERIODS_PER_DAY

FILLER_CODE = "STUDY"


def _check_slot(slot: int) -> None:
    if not 0 <= slot < SLOT_COUNT:
        raise ValueError(f"slot {slot} outside 0..{SLOT_COUNT - 1}")


def day_of(slot: int) -> int:
    _check_slot(slot)
    return slot // PERIODS_PER_DAY


def period_of(slot: int) -> int:
    _check_slot(slot)
    return slot % PERIODS_PER_DAY


def slots_of_day(day: int) -> list[int]:
    if not 0 <= day < DAYS:
        raise ValueError(f"day {day} outside 0..{DAYS - 1}")
    start = day * PERIODS_PER_DAY
    return list(range(start, start + PERIODS_PER_DAY))


def adjacent_pairs_of_day(day: int) -> list[tuple[int, int]]:
    """The 9 consecutive slot pairs inside one day. Never spans days."""
    slots = slots_of_day(day)
    return [(slots[i], slots[i + 1]) for i in range(PERIODS_PER_DAY - 1)]


def all_adjacent_pairs() -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for day in range(DAYS):
        pairs.extend(adjacent_pairs_of_day(day))
    return pairs


def is_adjacent(a: int, b: int) -> bool:
    """True when a and b are consecutive slots within the same day."""
    _check_slot(a)
    _check_slot(b)
    return day_of(a) == day_of(b) and abs(a - b) == 1
