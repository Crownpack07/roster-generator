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


@dataclass(frozen=True, order=True)
class ClassRef:
    grade: int
    section: str

    def __str__(self) -> str:
        return f"{self.grade}{self.section}"


@dataclass(frozen=True)
class Subject:
    code: str
    display_name: str
    is_core: bool
    is_optional: bool


@dataclass(frozen=True)
class Teacher:
    id: str
    name: str
    blocked_slots: frozenset[int] = frozenset()


@dataclass(frozen=True)
class Block:
    teacher_id: str
    grade: int
    subject_code: str
    sections: tuple[str, ...]
    periods_per_class: int

    def __post_init__(self) -> None:
        if not self.sections:
            raise ValueError("a block must cover at least one section")
        if len(set(self.sections)) != len(self.sections):
            raise ValueError(f"duplicate sections in block {self.sections!r}")

    @property
    def total_periods(self) -> int:
        return self.periods_per_class * len(self.sections)

    def class_refs(self) -> tuple[ClassRef, ...]:
        return tuple(ClassRef(self.grade, s) for s in self.sections)


@dataclass(frozen=True)
class Placement:
    class_ref: ClassRef
    subject_code: str
    slot: int


@dataclass(frozen=True)
class Schedule:
    placements: tuple[Placement, ...] = ()

    def for_class(self, class_ref: ClassRef) -> dict[int, str]:
        return {
            p.slot: p.subject_code
            for p in self.placements
            if p.class_ref == class_ref
        }

    def slots_of(self, class_ref: ClassRef, subject_code: str) -> list[int]:
        return sorted(
            p.slot
            for p in self.placements
            if p.class_ref == class_ref and p.subject_code == subject_code
        )
