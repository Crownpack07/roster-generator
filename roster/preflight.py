"""Layer 1: arithmetic checks that run before the solver.

Most real failures are counting errors, and arithmetic explains them far
better than an UNSAT core can.
"""

from __future__ import annotations

from dataclasses import dataclass

from roster.allocation import (
    caps_deviation,
    demand,
    filler_periods,
    required_periods,
)
from roster.domain import DAYS, PERIODS_PER_DAY, SLOT_COUNT, day_of
from roster.problem import Problem, coverage_problems

CORE_MIN_PERIODS = DAYS  # at least one a day
CORE_MAX_PERIODS = 2 * DAYS  # at most two a day


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # "error" | "warning"
    message: str


def has_errors(findings: list[Finding]) -> bool:
    return any(f.severity == "error" for f in findings)


def _forced_periods_per_day(problem: Problem, grade: int, code: str) -> int:
    """The minimum this subject must occupy on any single day, per class."""
    n = demand(problem.scenario, grade).get(code, 0)
    if not n:
        return 0
    if problem.is_core(code):
        # Held to at most 2 a day across 6 days, so n periods force
        # max(1, n - 2*(DAYS-1)) on every day.
        return max(1, n - 2 * (DAYS - 1))
    return 0


def _check_curriculum_bounds(problem: Problem) -> list[Finding]:
    out: list[Finding] = []
    for grade in problem.grades:
        for code, n in demand(problem.scenario, grade).items():
            if not problem.is_core(code):
                continue
            if n < CORE_MIN_PERIODS:
                out.append(
                    Finding(
                        "curriculum_bounds",
                        "error",
                        f"Grade {grade} {code} has {n} periods but must appear "
                        f"on all {DAYS} days of the cycle. It needs at least "
                        f"{CORE_MIN_PERIODS}.",
                    )
                )
            elif n > CORE_MAX_PERIODS:
                out.append(
                    Finding(
                        "curriculum_bounds",
                        "error",
                        f"Grade {grade} {code} has {n} periods but a core "
                        f"subject may run at most 2 periods a day, so at most "
                        f"{CORE_MAX_PERIODS} across the cycle.",
                    )
                )
    return out


def _check_class_totals(problem: Problem) -> list[Finding]:
    out: list[Finding] = []
    for grade in problem.grades:
        required = sum(required_periods(problem.scenario, grade).values())
        filler = filler_periods(problem.scenario, grade)
        if filler < 0:
            out.append(
                Finding(
                    "class_total",
                    "error",
                    f"Grade {grade} needs {required} periods but only "
                    f"{SLOT_COUNT} slots exist — {abs(filler)} too many. Turn "
                    f"an optional subject off, or override a curriculum count.",
                )
            )
    return out


def _check_coverage(problem: Problem) -> list[Finding]:
    out: list[Finding] = []
    for kind, class_ref, code, count in coverage_problems(problem):
        if kind == "unassigned":
            out.append(
                Finding(
                    "coverage",
                    "error",
                    f"{class_ref} {code} has no teacher assigned.",
                )
            )
        else:
            out.append(
                Finding(
                    "coverage",
                    "error",
                    f"{class_ref} {code} is assigned to {count} blocks; "
                    f"it must be assigned exactly once.",
                )
            )
    return out


def _check_block_wholeness(problem: Problem) -> list[Finding]:
    """A block must cover every class of its grade.

    One teacher owns a subject for a whole grade, so a (grade, subject) split
    between two teachers is a configuration error rather than a supported
    arrangement.
    """
    out: list[Finding] = []
    for block in problem.blocks:
        missing = [s for s in problem.sections if s not in block.sections]
        if missing:
            teacher = problem.teachers.get(block.teacher_id)
            name = teacher.name if teacher else block.teacher_id
            out.append(
                Finding(
                    "block_wholeness",
                    "error",
                    f"{name} holds Gr{block.grade} {block.subject_code} for "
                    f"only {', '.join(block.sections)} — a subject must be "
                    f"taught to the whole grade by one teacher. Missing: "
                    f"{', '.join(missing)}.",
                )
            )
    return out


def _check_block_periods(problem: Problem) -> list[Finding]:
    """A block's stored period count must match the curriculum it serves.

    The count is stored so the editor and the database can show it, which
    means it can drift from the curriculum. This catches that.
    """
    out: list[Finding] = []
    for block in problem.blocks:
        wanted = demand(problem.scenario, block.grade).get(block.subject_code)
        if wanted is None:
            out.append(
                Finding(
                    "block_periods",
                    "error",
                    f"Gr{block.grade} {block.subject_code} is assigned but "
                    f"grade {block.grade} does not take it.",
                )
            )
        elif wanted != block.periods_per_class:
            out.append(
                Finding(
                    "block_periods",
                    "error",
                    f"Gr{block.grade} {block.subject_code} is assigned "
                    f"{block.periods_per_class} periods per class but the "
                    f"curriculum says {wanted}.",
                )
            )
    return out


def _check_teacher_capacity(problem: Problem) -> list[Finding]:
    out: list[Finding] = []
    for teacher_id, teacher in problem.teachers.items():
        load = problem.teacher_load(teacher_id)
        available = SLOT_COUNT - len(teacher.blocked_slots)
        if load > available:
            detail = ", ".join(
                f"Gr{b.grade} {b.subject_code} {b.total_periods}"
                for b in problem.blocks_of(teacher_id)
            )
            blocked_note = (
                f" ({len(teacher.blocked_slots)} slots blocked)"
                if teacher.blocked_slots
                else ""
            )
            out.append(
                Finding(
                    "teacher_capacity",
                    "error",
                    f"{teacher.name} is assigned {load} periods; only "
                    f"{available} of {SLOT_COUNT} are available"
                    f"{blocked_note}. Blocks: {detail}.",
                )
            )
    return out


def _check_teacher_daily_floor(problem: Problem) -> list[Finding]:
    out: list[Finding] = []
    for teacher_id, teacher in problem.teachers.items():
        forced = 0
        parts: list[str] = []
        for block in problem.blocks_of(teacher_id):
            per_day = _forced_periods_per_day(
                problem, block.grade, block.subject_code
            )
            if per_day:
                cost = per_day * len(block.sections)
                forced += cost
                parts.append(
                    f"Gr{block.grade} {block.subject_code} {cost}"
                )
        if forced > PERIODS_PER_DAY:
            out.append(
                Finding(
                    "teacher_daily_floor",
                    "error",
                    f"{teacher.name} is forced into {forced} periods every day "
                    f"but a day is only {PERIODS_PER_DAY} periods long. "
                    f"Daily minimums: {', '.join(parts)}.",
                )
            )
    return out


def _check_blocked_day_conflicts(problem: Problem) -> list[Finding]:
    out: list[Finding] = []
    for teacher_id, teacher in problem.teachers.items():
        if not teacher.blocked_slots:
            continue
        for day in range(DAYS):
            day_slots = {
                s for s in teacher.blocked_slots if day_of(s) == day
            }
            if len(day_slots) < PERIODS_PER_DAY:
                continue
            for block in problem.blocks_of(teacher_id):
                if problem.is_core(block.subject_code):
                    out.append(
                        Finding(
                            "blocked_day_conflict",
                            "error",
                            f"{teacher.name} is blocked for all of day "
                            f"{day + 1} but holds Gr{block.grade} "
                            f"{block.subject_code}, which must appear every "
                            f"day.",
                        )
                    )
    return out


def _warn_caps_deviation(problem: Problem) -> list[Finding]:
    out: list[Finding] = []
    for grade in problem.grades:
        deviations = {
            code: diff
            for code, diff in caps_deviation(problem.scenario, grade).items()
            if diff
        }
        if deviations:
            detail = ", ".join(
                f"{code} {diff:+d}" for code, diff in sorted(deviations.items())
            )
            out.append(
                Finding(
                    "caps_deviation",
                    "warning",
                    f"Grade {grade} deviates from CAPS: {detail}.",
                )
            )
    return out


def _warn_load_spread(problem: Problem) -> list[Finding]:
    loads = {
        t: problem.teacher_load(t) for t in problem.teachers
    }
    if not loads:
        return []
    lowest = min(loads, key=lambda t: loads[t])
    highest = max(loads, key=lambda t: loads[t])
    spread = loads[highest] - loads[lowest]
    if spread == 0:
        return []
    return [
        Finding(
            "load_spread",
            "warning",
            f"Teaching load ranges over {spread} periods — "
            f"{problem.teachers[highest].name} {loads[highest]}, "
            f"{problem.teachers[lowest].name} {loads[lowest]}. The solver "
            f"cannot change this; only the assignment can.",
        )
    ]


def _warn_optional_off(problem: Problem) -> list[Finding]:
    all_optional = {
        code
        for code, subject in problem.subjects.items()
        if subject.is_optional
    }
    off = sorted(all_optional - problem.scenario.enabled_optional)
    if not off:
        return []
    return [
        Finding(
            "optional_off",
            "warning",
            f"Optional subjects currently switched off: {', '.join(off)}.",
        )
    ]


def preflight(problem: Problem) -> list[Finding]:
    """Every arithmetic finding, errors first."""
    errors: list[Finding] = []
    errors += _check_curriculum_bounds(problem)
    errors += _check_class_totals(problem)
    errors += _check_coverage(problem)
    errors += _check_block_wholeness(problem)
    errors += _check_block_periods(problem)
    errors += _check_teacher_capacity(problem)
    errors += _check_teacher_daily_floor(problem)
    errors += _check_blocked_day_conflicts(problem)

    warnings: list[Finding] = []
    warnings += _warn_caps_deviation(problem)
    warnings += _warn_load_spread(problem)
    warnings += _warn_optional_off(problem)

    return errors + warnings
