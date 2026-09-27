"""CP-SAT encoding.

One boolean per (class, subject, slot): "this class studies this subject in
this slot". Teacher occupancy is derived, because each (class, subject) pair
maps to exactly one block, which names the teacher.

Every rule group is guarded by an assumption literal so an infeasible model
can report which groups conflict.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from roster.allocation import doubles_ceiling, max_per_day
from roster.domain import (
    DAYS,
    SLOT_COUNT,
    ClassRef,
    Placement,
    Schedule,
    adjacent_pairs_of_day,
    slots_of_day,
)
from roster.problem import Problem

RULE_SLOT_FILLED = "slot_filled"
RULE_PERIOD_COUNTS = "period_counts"
RULE_TEACHER_CLASH = "teacher_clash"
RULE_BLOCKED_SLOTS = "blocked_slots"
RULE_CORE_DAILY = "core_daily"
RULE_SPREAD = "spread"
RULE_MIN_DOUBLES = "min_doubles"

ALL_RULES = (
    RULE_SLOT_FILLED,
    RULE_PERIOD_COUNTS,
    RULE_TEACHER_CLASH,
    RULE_BLOCKED_SLOTS,
    RULE_CORE_DAILY,
    RULE_SPREAD,
    RULE_MIN_DOUBLES,
)

CORE_MIN_PER_DAY = 1
CORE_MAX_PER_DAY = 2


@dataclass
class BuiltModel:
    model: cp_model.CpModel
    x: dict[tuple[ClassRef, str, int], cp_model.IntVar] = field(
        default_factory=dict
    )
    doubles: dict[
        tuple[ClassRef, str, tuple[int, int]], cp_model.IntVar
    ] = field(default_factory=dict)
    assumptions: dict[str, cp_model.IntVar] = field(default_factory=dict)


def build(problem: Problem) -> BuiltModel:
    model = cp_model.CpModel()
    built = BuiltModel(model=model)

    for rule in ALL_RULES:
        built.assumptions[rule] = model.NewBoolVar(f"assume_{rule}")
        model.AddAssumption(built.assumptions[rule])

    # Variables.
    for class_ref in problem.classes():
        for code in problem.demand_for(class_ref.grade):
            for slot in range(SLOT_COUNT):
                built.x[(class_ref, code, slot)] = model.NewBoolVar(
                    f"x_{class_ref}_{code}_{slot}"
                )

    _add_slot_filled(problem, built)
    _add_period_counts(problem, built)
    _add_teacher_rules(problem, built)
    _add_core_daily(problem, built)
    _add_spread(problem, built)
    _add_doubles(problem, built)
    _set_objective(built)
    return built


def _add_slot_filled(problem: Problem, built: BuiltModel) -> None:
    guard = built.assumptions[RULE_SLOT_FILLED]
    for class_ref in problem.classes():
        codes = list(problem.demand_for(class_ref.grade))
        for slot in range(SLOT_COUNT):
            terms = [built.x[(class_ref, c, slot)] for c in codes]
            built.model.Add(sum(terms) == 1).OnlyEnforceIf(guard)


def _add_period_counts(problem: Problem, built: BuiltModel) -> None:
    guard = built.assumptions[RULE_PERIOD_COUNTS]
    for class_ref in problem.classes():
        for code, n in problem.demand_for(class_ref.grade).items():
            terms = [
                built.x[(class_ref, code, slot)] for slot in range(SLOT_COUNT)
            ]
            built.model.Add(sum(terms) == n).OnlyEnforceIf(guard)


def _add_teacher_rules(problem: Problem, built: BuiltModel) -> None:
    clash_guard = built.assumptions[RULE_TEACHER_CLASH]
    blocked_guard = built.assumptions[RULE_BLOCKED_SLOTS]

    owned: dict[str, list[tuple[ClassRef, str]]] = defaultdict(list)
    for class_ref in problem.classes():
        for code in problem.demand_for(class_ref.grade):
            block = problem.block_for(class_ref, code)
            if block is not None:
                owned[block.teacher_id].append((class_ref, code))

    for teacher_id, pairs in owned.items():
        teacher = problem.teachers[teacher_id]
        for slot in range(SLOT_COUNT):
            terms = [built.x[(c, code, slot)] for c, code in pairs]
            if not terms:
                continue
            if slot in teacher.blocked_slots:
                built.model.Add(sum(terms) == 0).OnlyEnforceIf(blocked_guard)
            else:
                built.model.Add(sum(terms) <= 1).OnlyEnforceIf(clash_guard)


def _add_core_daily(problem: Problem, built: BuiltModel) -> None:
    guard = built.assumptions[RULE_CORE_DAILY]
    for class_ref in problem.classes():
        for code in problem.demand_for(class_ref.grade):
            if not problem.is_core(code):
                continue
            for day in range(DAYS):
                terms = [
                    built.x[(class_ref, code, slot)]
                    for slot in slots_of_day(day)
                ]
                built.model.Add(sum(terms) >= CORE_MIN_PER_DAY).OnlyEnforceIf(
                    guard
                )
                built.model.Add(sum(terms) <= CORE_MAX_PER_DAY).OnlyEnforceIf(
                    guard
                )


def _add_spread(problem: Problem, built: BuiltModel) -> None:
    guard = built.assumptions[RULE_SPREAD]
    for class_ref in problem.classes():
        for code, n in problem.demand_for(class_ref.grade).items():
            if problem.is_core(code):
                continue
            cap = max_per_day(n)
            for day in range(DAYS):
                terms = [
                    built.x[(class_ref, code, slot)]
                    for slot in slots_of_day(day)
                ]
                built.model.Add(sum(terms) <= cap).OnlyEnforceIf(guard)


def _add_doubles(problem: Problem, built: BuiltModel) -> None:
    """One reified variable per (class, core subject, same-day adjacent pair).

    Because a core subject runs at most twice a day, at most one pair per day
    can be true, so summing these variables counts doubles without the
    triple-counting a longer run would cause.
    """
    guard = built.assumptions[RULE_MIN_DOUBLES]
    for class_ref in problem.classes():
        for code in problem.demand_for(class_ref.grade):
            if not problem.is_core(code):
                continue
            pair_vars: list[cp_model.IntVar] = []
            for day in range(DAYS):
                for a, b in adjacent_pairs_of_day(day):
                    y = built.model.NewBoolVar(f"d_{class_ref}_{code}_{a}")
                    xa = built.x[(class_ref, code, a)]
                    xb = built.x[(class_ref, code, b)]
                    built.model.Add(y <= xa)
                    built.model.Add(y <= xb)
                    built.model.Add(y >= xa + xb - 1)
                    built.doubles[(class_ref, code, (a, b))] = y
                    pair_vars.append(y)
            minimum = problem.scenario.min_doubles.get(
                (class_ref.grade, code), 0
            )
            if minimum:
                built.model.Add(sum(pair_vars) >= minimum).OnlyEnforceIf(guard)


def _set_objective(built: BuiltModel) -> None:
    """Maximise total doubles. This is the only objective."""
    built.model.Maximize(sum(built.doubles.values()))


def total_doubles_ceiling(problem: Problem) -> int:
    """Doubles achievable across every class, summed."""
    total = 0
    for class_ref in problem.classes():
        for code, n in problem.demand_for(class_ref.grade).items():
            if problem.is_core(code):
                total += doubles_ceiling(n)
    return total


def schedule_from(
    problem: Problem, built: BuiltModel, solver: cp_model.CpSolver
) -> Schedule:
    placements: list[Placement] = []
    for (class_ref, code, slot), var in built.x.items():
        if solver.Value(var):
            placements.append(Placement(class_ref, code, slot))
    placements.sort(key=lambda p: (p.class_ref, p.slot))
    return Schedule(tuple(placements))
