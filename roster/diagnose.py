"""Layer 2: turn an UNSAT core into English sentences and ranked remedies.

Each rule group in the model carries an assumption literal. When the model is
infeasible, CP-SAT returns the smallest set of those literals that cannot all
hold. This module maps them back to sentences a person can act on.
"""

from __future__ import annotations

from dataclasses import dataclass

from roster.domain import DAYS, PERIODS_PER_DAY, SLOT_COUNT
from roster.model import (
    RULE_BLOCKED_SLOTS,
    RULE_CORE_DAILY,
    RULE_MIN_DOUBLES,
    RULE_PERIOD_COUNTS,
    RULE_SLOT_FILLED,
    RULE_SPREAD,
    RULE_TEACHER_CLASH,
)
from roster.problem import Problem

RULE_SENTENCES: dict[str, str] = {
    RULE_SLOT_FILLED: (
        f"Every class must have exactly one subject in each of its "
        f"{SLOT_COUNT} slots."
    ),
    RULE_PERIOD_COUNTS: (
        "Every subject must hit its exact period count for the cycle."
    ),
    RULE_TEACHER_CLASH: (
        "No teacher can be with two classes in the same period."
    ),
    RULE_BLOCKED_SLOTS: (
        "Teachers cannot be scheduled in slots marked unavailable."
    ),
    RULE_CORE_DAILY: (
        f"Home Language, First Additional Language and Mathematics must each "
        f"appear on all {DAYS} days, at most twice a day."
    ),
    RULE_SPREAD: (
        "Non-core subjects must spread across the cycle rather than clump "
        "into one day."
    ),
    RULE_MIN_DOUBLES: (
        "Subjects with a minimum double-period count must reach it."
    ),
}


@dataclass(frozen=True)
class ConflictReport:
    rule_groups: tuple[str, ...] = ()
    sentences: tuple[str, ...] = ()
    remedies: tuple[str, ...] = ()


def _spare_capacity(problem: Problem) -> list[tuple[str, int]]:
    """Teachers with room, most spare first."""
    spare = []
    for teacher_id, teacher in problem.teachers.items():
        available = SLOT_COUNT - len(teacher.blocked_slots)
        room = available - problem.teacher_load(teacher_id)
        if room > 0:
            spare.append((teacher.name, room))
    spare.sort(key=lambda pair: -pair[1])
    return spare


def remedies_for(
    problem: Problem, rule_groups: tuple[str, ...]
) -> tuple[str, ...]:
    """Ranked smallest changes that could restore feasibility."""
    out: list[str] = []

    if RULE_MIN_DOUBLES in rule_groups:
        wanted = ", ".join(
            f"Gr{grade} {code} (minimum {n})"
            for (grade, code), n in sorted(problem.scenario.min_doubles.items())
        )
        out.append(
            f"Lower or remove the double-period minimum. Currently set: "
            f"{wanted or 'none'}. The default is 0, which lets the objective "
            f"earn doubles instead of demanding them."
        )

    if RULE_TEACHER_CLASH in rule_groups or RULE_BLOCKED_SLOTS in rule_groups:
        spare = _spare_capacity(problem)
        if spare:
            listed = ", ".join(
                f"{name} (+{room} free)" for name, room in spare[:3]
            )
            out.append(
                f"Reassign one of the conflicting blocks to a teacher with "
                f"room: {listed}."
            )
        else:
            out.append(
                "Reassign one of the conflicting blocks. No teacher currently "
                "has spare capacity, so a block has to move off someone else "
                "first."
            )

    if RULE_BLOCKED_SLOTS in rule_groups:
        blocked = [
            (t.name, len(t.blocked_slots))
            for t in problem.teachers.values()
            if t.blocked_slots
        ]
        if blocked:
            listed = ", ".join(
                f"{name} ({count} slots)" for name, count in sorted(blocked)
            )
            out.append(f"Free up blocked slots: {listed}.")

    if RULE_CORE_DAILY in rule_groups:
        out.append(
            f"Allow a core subject to miss a day, or to run more than twice "
            f"in one day. Both are currently hard rules and a day is only "
            f"{PERIODS_PER_DAY} periods long."
        )

    if RULE_SPREAD in rule_groups:
        out.append(
            "Raise the daily cap on a non-core subject so it may run more "
            "than once in a day."
        )

    if RULE_PERIOD_COUNTS in rule_groups or RULE_SLOT_FILLED in rule_groups:
        out.append(
            "Change a period count: turn an optional subject off, or override "
            "a curriculum count so the grade's total fits "
            f"{SLOT_COUNT} slots."
        )

    return tuple(out)


def explain(problem: Problem, built, solver) -> ConflictReport:
    """Read the UNSAT core off the solver and translate it.

    Returns an empty report when the model was not infeasible.
    """
    try:
        indices = solver.SufficientAssumptionsForInfeasibility()
    except Exception:  # solver holds no core for a feasible solve
        return ConflictReport()

    if not indices:
        return ConflictReport()

    by_index = {
        var.Index(): rule for rule, var in built.assumptions.items()
    }
    groups = tuple(
        dict.fromkeys(
            by_index[i] for i in indices if i in by_index
        )
    )
    if not groups:
        return ConflictReport()

    sentences = tuple(RULE_SENTENCES[g] for g in groups)
    return ConflictReport(
        rule_groups=groups,
        sentences=sentences,
        remedies=remedies_for(problem, groups),
    )
