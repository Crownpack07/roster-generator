"""Independent verification of a finished schedule.

This module deliberately shares no code with the constraint model. It
re-derives every hard rule from the problem so a mistake in the model
cannot be mirrored by a matching mistake in the check.

Do not import ortools or roster.model here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from roster.allocation import demand, max_per_day
from roster.domain import (
    DAYS,
    SLOT_COUNT,
    ClassRef,
    Placement,
    Schedule,
    day_of,
    is_adjacent,
)
from roster.problem import Problem

CORE_MIN_PER_DAY = 1
CORE_MAX_PER_DAY = 2


@dataclass(frozen=True)
class Violation:
    code: str
    message: str


def verify(problem: Problem, schedule: Schedule) -> list[Violation]:
    """Every way this schedule breaks a hard rule. Empty means valid."""
    out: list[Violation] = []
    out += _check_unknown_subjects(problem, schedule)
    out += _check_unknown_teachers(problem)
    out += _check_slots_filled_once(problem, schedule)
    out += _check_period_counts(problem, schedule)
    out += _check_teacher_clashes(problem, schedule)
    out += _check_blocked_slots(problem, schedule)
    out += _check_core_daily(problem, schedule)
    out += _check_spread(problem, schedule)
    return out


def _by_class(schedule: Schedule) -> dict[ClassRef, dict[int, list[str]]]:
    table: dict[ClassRef, dict[int, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for p in schedule.placements:
        table[p.class_ref][p.slot].append(p.subject_code)
    return table


def _check_unknown_subjects(
    problem: Problem, schedule: Schedule
) -> list[Violation]:
    out: list[Violation] = []
    for p in schedule.placements:
        wanted = demand(problem.scenario, p.class_ref.grade)
        if p.subject_code not in wanted:
            out.append(
                Violation(
                    "unknown_subject",
                    f"{p.class_ref} is scheduled for {p.subject_code} in slot "
                    f"{p.slot}, which grade {p.class_ref.grade} does not take.",
                )
            )
    return out


def _check_unknown_teachers(problem: Problem) -> list[Violation]:
    """Pre-flight rejects these, but verify() may be called without it.

    The teacher checks below skip such blocks and report them here, rather
    than raise a KeyError.
    """
    return [
        Violation(
            "unknown_teacher",
            f"Gr{b.grade} {b.subject_code} is assigned to teacher "
            f"{b.teacher_id}, who is not on the staff list.",
        )
        for b in problem.blocks
        if b.teacher_id not in problem.teachers
    ]


def _teacher_block(problem: Problem, p: Placement):
    """The block behind a placement, if it names a known teacher."""
    block = problem.block_for(p.class_ref, p.subject_code)
    if block is None or block.teacher_id not in problem.teachers:
        return None
    return block


def _check_slots_filled_once(
    problem: Problem, schedule: Schedule
) -> list[Violation]:
    out: list[Violation] = []
    table = _by_class(schedule)
    for class_ref in problem.classes():
        slots = table.get(class_ref, {})
        for slot in range(SLOT_COUNT):
            subjects = slots.get(slot, [])
            if not subjects:
                out.append(
                    Violation(
                        "slot_not_filled",
                        f"{class_ref} has nothing scheduled in slot {slot} "
                        f"(day {day_of(slot) + 1}).",
                    )
                )
            elif len(subjects) > 1:
                out.append(
                    Violation(
                        "slot_double_booked",
                        f"{class_ref} has {len(subjects)} subjects in slot "
                        f"{slot}: {', '.join(sorted(subjects))}.",
                    )
                )
    return out


def _check_period_counts(
    problem: Problem, schedule: Schedule
) -> list[Violation]:
    out: list[Violation] = []
    for class_ref in problem.classes():
        wanted = demand(problem.scenario, class_ref.grade)
        for code, expected in wanted.items():
            actual = len(schedule.slots_of(class_ref, code))
            if actual != expected:
                out.append(
                    Violation(
                        "period_count",
                        f"{class_ref} {code} has {actual} periods, expected "
                        f"{expected}.",
                    )
                )
    return out


def _check_teacher_clashes(
    problem: Problem, schedule: Schedule
) -> list[Violation]:
    occupied: dict[tuple[str, int], list[str]] = defaultdict(list)
    for p in schedule.placements:
        block = _teacher_block(problem, p)
        if block is None:
            continue
        occupied[(block.teacher_id, p.slot)].append(
            f"{p.class_ref} {p.subject_code}"
        )
    out: list[Violation] = []
    for (teacher_id, slot), entries in sorted(occupied.items()):
        if len(entries) > 1:
            name = problem.teachers[teacher_id].name
            out.append(
                Violation(
                    "teacher_clash",
                    f"{name} is in {len(entries)} places in slot {slot}: "
                    f"{', '.join(sorted(entries))}.",
                )
            )
    return out


def _check_blocked_slots(
    problem: Problem, schedule: Schedule
) -> list[Violation]:
    out: list[Violation] = []
    for p in schedule.placements:
        block = _teacher_block(problem, p)
        if block is None:
            continue
        teacher = problem.teachers[block.teacher_id]
        if p.slot in teacher.blocked_slots:
            out.append(
                Violation(
                    "blocked_slot",
                    f"{teacher.name} is scheduled in slot {p.slot} for "
                    f"{p.class_ref} {p.subject_code}, but that slot is "
                    f"blocked.",
                )
            )
    return out


def _check_core_daily(
    problem: Problem, schedule: Schedule
) -> list[Violation]:
    out: list[Violation] = []
    for class_ref in problem.classes():
        wanted = demand(problem.scenario, class_ref.grade)
        for code in wanted:
            if not problem.is_core(code):
                continue
            slots = schedule.slots_of(class_ref, code)
            per_day = [0] * DAYS
            for slot in slots:
                per_day[day_of(slot)] += 1
            for day, count in enumerate(per_day):
                if count < CORE_MIN_PER_DAY:
                    out.append(
                        Violation(
                            "core_daily",
                            f"{class_ref} {code} does not appear on day "
                            f"{day + 1}; a core subject must appear every day.",
                        )
                    )
                elif count > CORE_MAX_PER_DAY:
                    out.append(
                        Violation(
                            "core_daily",
                            f"{class_ref} {code} has {count} periods on day "
                            f"{day + 1}; at most {CORE_MAX_PER_DAY} allowed.",
                        )
                    )
    return out


def _check_spread(problem: Problem, schedule: Schedule) -> list[Violation]:
    out: list[Violation] = []
    for class_ref in problem.classes():
        wanted = demand(problem.scenario, class_ref.grade)
        for code, n in wanted.items():
            if problem.is_core(code):
                continue
            cap = max_per_day(n)
            per_day = [0] * DAYS
            for slot in schedule.slots_of(class_ref, code):
                per_day[day_of(slot)] += 1
            for day, count in enumerate(per_day):
                if count > cap:
                    out.append(
                        Violation(
                            "spread",
                            f"{class_ref} {code} has {count} periods on day "
                            f"{day + 1}; at most {cap} allowed for "
                            f"{n} periods across {DAYS} days.",
                        )
                    )
    return out


def count_doubles(problem: Problem, schedule: Schedule) -> int:
    """Same-day adjacent pairs of a core subject. Never spans days."""
    total = 0
    for class_ref in problem.classes():
        wanted = demand(problem.scenario, class_ref.grade)
        for code in wanted:
            if not problem.is_core(code):
                continue
            slots = schedule.slots_of(class_ref, code)
            for i in range(len(slots) - 1):
                if is_adjacent(slots[i], slots[i + 1]):
                    total += 1
    return total
