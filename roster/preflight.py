"""Layer 1: arithmetic checks that run before the solver.

Most real failures are counting errors, and arithmetic explains them far
better than an UNSAT core can.
"""

from __future__ import annotations

from dataclasses import dataclass

from roster.allocation import (
    caps_deviation,
    demand,
    doubles_ceiling,
    filler_periods,
    max_per_day,
    required_periods,
)
from roster.domain import (
    DAYS,
    FILLER_CODE,
    PERIODS_PER_DAY,
    SLOT_COUNT,
    day_of,
)
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
    """The fewest periods this subject can have on any single day, per class.

    Whatever the other five days hold at their cap, the rest lands here. A
    core subject is capped at 2 a day and must also appear daily; a non-core
    one is capped at ceil(n / 6). A 6-period non-core subject therefore runs
    every day too.
    """
    n = demand(problem.scenario, grade).get(code, 0)
    if not n:
        return 0
    if problem.is_core(code):
        return max(1, n - 2 * (DAYS - 1))
    return max(0, n - max_per_day(n) * (DAYS - 1))


def _join(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _check_integrity(problem: Problem) -> list[Finding]:
    """Every reference must resolve before any arithmetic is trusted.

    An unknown subject would otherwise count as non-core, silently dropping
    its daily rule; an unknown teacher or an out-of-range slot crashes the
    later checks and the model.
    """
    out: list[Finding] = []
    unknown: dict[str, list[str]] = {}
    for grade in problem.grades:
        for code in problem.demand_for(grade):
            if code != FILLER_CODE and code not in problem.subjects:
                unknown.setdefault(code, []).append(str(grade))
    for code, grades in unknown.items():
        noun = "Grade" if len(grades) == 1 else "Grades"
        out.append(
            Finding(
                "integrity",
                "error",
                f"{noun} {_join(grades)} take {code}, but there is no "
                f"subject {code}. Add the subject, or remove it from the "
                f"curriculum.",
            )
        )

    for block in problem.blocks:
        teacher = problem.teachers.get(block.teacher_id)
        name = teacher.name if teacher else block.teacher_id
        if block.grade not in problem.grades:
            out.append(
                Finding(
                    "integrity",
                    "error",
                    f"{name} is assigned Gr{block.grade} "
                    f"{block.subject_code}, but the school has no grade "
                    f"{block.grade}.",
                )
            )
        stale = [s for s in block.sections if s not in problem.sections]
        if stale:
            noun = "section" if len(stale) == 1 else "sections"
            out.append(
                Finding(
                    "integrity",
                    "error",
                    f"{name} is assigned Gr{block.grade} "
                    f"{block.subject_code} for {noun} {_join(stale)}, "
                    f"which the school does not have.",
                )
            )
        if teacher is None:
            out.append(
                Finding(
                    "integrity",
                    "error",
                    f"Gr{block.grade} {block.subject_code} is assigned to "
                    f"teacher {block.teacher_id}, who is not on the staff "
                    f"list.",
                )
            )
        if block.subject_code not in problem.subjects and (
            block.subject_code not in unknown
        ):
            out.append(
                Finding(
                    "integrity",
                    "error",
                    f"{name} is assigned Gr{block.grade} {block.subject_code}, "
                    f"but there is no subject {block.subject_code}.",
                )
            )

    for teacher in problem.teachers.values():
        bad = sorted(s for s in teacher.blocked_slots if not 0 <= s < SLOT_COUNT)
        if bad:
            out.append(
                Finding(
                    "integrity",
                    "error",
                    f"{teacher.name} has blocked slots "
                    f"{', '.join(map(str, bad))}, outside the cycle's slots "
                    f"0 to {SLOT_COUNT - 1}.",
                )
            )
    return out


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
    """Per teacher and day: the periods the rules force onto that day
    against the periods the teacher has free on it.

    Days that fail with the same numbers are reported together, so an
    unblocked teacher who overflows every day gets one finding, not six.
    """
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
                parts.append(f"Gr{block.grade} {block.subject_code} {cost}")
        if not forced:
            continue

        failing: dict[int, list[str]] = {}
        for day in range(DAYS):
            blocked = sum(1 for s in teacher.blocked_slots if day_of(s) == day)
            if forced > PERIODS_PER_DAY - blocked:
                failing.setdefault(blocked, []).append(str(day + 1))
        for blocked, days in failing.items():
            available = PERIODS_PER_DAY - blocked
            when = (
                f"day {days[0]}" if len(days) == 1 else f"days {_join(days)}"
            )
            room = (
                f"only {available} of the day's {PERIODS_PER_DAY} periods "
                f"are free ({blocked} blocked)"
                if blocked
                else f"a day is only {PERIODS_PER_DAY} periods long"
            )
            out.append(
                Finding(
                    "teacher_daily_floor",
                    "error",
                    f"{teacher.name} is forced into {forced} periods on "
                    f"{when}, but {room}. Daily minimums: {', '.join(parts)}.",
                )
            )
    return out


def _check_min_doubles(problem: Problem) -> list[Finding]:
    """A minimum above the ceiling is impossible; one the model never
    reads is a setting the user believes is in force."""
    out: list[Finding] = []
    for (grade, code), minimum in sorted(problem.scenario.min_doubles.items()):
        n = (
            problem.demand_for(grade).get(code, 0)
            if grade in problem.grades
            else 0
        )
        if not n:
            out.append(
                Finding(
                    "min_doubles",
                    "warning",
                    f"A double-period minimum of {minimum} is set for "
                    f"Gr{grade} {code}, but grade {grade} does not take "
                    f"{code}, so it is ignored.",
                )
            )
        elif not problem.is_core(code):
            out.append(
                Finding(
                    "min_doubles",
                    "warning",
                    f"A double-period minimum of {minimum} is set for "
                    f"Gr{grade} {code}, but only core subjects are paired "
                    f"into doubles, so it is ignored.",
                )
            )
        elif not CORE_MIN_PERIODS <= n <= CORE_MAX_PERIODS:
            continue  # curriculum_bounds reports this; no ceiling to quote
        elif minimum > doubles_ceiling(n):
            out.append(
                Finding(
                    "min_doubles",
                    "error",
                    f"Gr{grade} {code} must have at least {minimum} doubles, "
                    f"but its {n} periods can form at most "
                    f"{doubles_ceiling(n)}: a core subject runs twice on at "
                    f"most {n - DAYS} of the {DAYS} days.",
                )
            )
    return out


def _warn_ignored_overrides(problem: Problem) -> list[Finding]:
    """An override only applies to a subject the grade actually takes."""
    out: list[Finding] = []
    scenario = problem.scenario
    for (grade, code), periods in sorted(scenario.overrides.items()):
        known = grade in problem.grades
        optional = known and code in scenario.optional.subject_codes(grade)
        taken = known and (
            code in scenario.caps.subject_codes(grade)
            or (optional and code in scenario.enabled_optional)
        )
        if taken:
            continue
        reason = (
            f"{code} is an optional subject that is switched off"
            if optional
            else f"grade {grade} does not take {code}"
        )
        out.append(
            Finding(
                "override_ignored",
                "warning",
                f"An override sets Gr{grade} {code} to {periods} periods, "
                f"but {reason}, so it is ignored.",
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
    """Every arithmetic finding, errors first.

    Integrity runs alone first: when a reference does not resolve, only its
    errors are returned, because the other checks would crash on or misread
    the same input.
    """
    integrity = _check_integrity(problem)
    if integrity:
        return integrity

    errors: list[Finding] = []
    errors += _check_curriculum_bounds(problem)
    errors += _check_class_totals(problem)
    errors += _check_coverage(problem)
    errors += _check_block_wholeness(problem)
    errors += _check_block_periods(problem)
    errors += _check_teacher_capacity(problem)
    errors += _check_teacher_daily_floor(problem)
    errors += _check_min_doubles(problem)

    warnings: list[Finding] = []
    warnings += _warn_caps_deviation(problem)
    warnings += _warn_load_spread(problem)
    warnings += _warn_optional_off(problem)
    warnings += _warn_ignored_overrides(problem)

    # _check_min_doubles returns both severities; keep errors first.
    return sorted(errors + warnings, key=lambda f: f.severity != "error")
