from ortools.sat.python import cp_model

from roster.domain import SLOT_COUNT, ClassRef
from roster.model import build, schedule_from
from roster.verify import verify
from tests.fixtures.meridian import meridian_problem


def solve_built(built, time_limit=30.0):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    status = solver.Solve(built.model)
    return solver, status


def test_variable_count_is_one_per_class_subject_slot():
    problem = meridian_problem()
    built = build(problem)
    expected = sum(
        len(problem.demand_for(c.grade)) * SLOT_COUNT
        for c in problem.classes()
    )
    assert len(built.x) == expected


def test_every_rule_group_has_an_assumption_literal():
    built = build(meridian_problem())
    from roster.model import (
        RULE_BLOCKED_SLOTS,
        RULE_CORE_DAILY,
        RULE_MIN_DOUBLES,
        RULE_PERIOD_COUNTS,
        RULE_SLOT_FILLED,
        RULE_SPREAD,
        RULE_TEACHER_CLASH,
    )

    for rule in (
        RULE_SLOT_FILLED,
        RULE_PERIOD_COUNTS,
        RULE_TEACHER_CLASH,
        RULE_BLOCKED_SLOTS,
        RULE_CORE_DAILY,
        RULE_SPREAD,
        RULE_MIN_DOUBLES,
    ):
        assert rule in built.assumptions


def test_model_solves_the_real_school_and_the_verifier_agrees():
    problem = meridian_problem()
    built = build(problem)
    solver, status = solve_built(built)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    schedule = schedule_from(problem, built, solver)
    assert verify(problem, schedule) == []


def test_every_class_slot_is_filled_exactly_once():
    problem = meridian_problem()
    built = build(problem)
    solver, status = solve_built(built)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    schedule = schedule_from(problem, built, solver)
    for class_ref in problem.classes():
        assert len(schedule.for_class(class_ref)) == SLOT_COUNT


def test_blocked_slots_are_left_empty_for_that_teacher():
    blocked = frozenset({0, 1, 2})
    problem = meridian_problem(blocked={"Karin": blocked})
    built = build(problem)
    solver, status = solve_built(built)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    schedule = schedule_from(problem, built, solver)
    for p in schedule.placements:
        block = problem.block_for(p.class_ref, p.subject_code)
        if block and block.teacher_id == "Karin":
            assert p.slot not in blocked


def test_teacher_never_appears_twice_in_one_slot():
    problem = meridian_problem()
    built = build(problem)
    solver, status = solve_built(built)
    schedule = schedule_from(problem, built, solver)
    seen: set[tuple[str, int]] = set()
    for p in schedule.placements:
        block = problem.block_for(p.class_ref, p.subject_code)
        assert block is not None
        key = (block.teacher_id, p.slot)
        assert key not in seen
        seen.add(key)


def test_schedule_from_returns_only_selected_variables():
    problem = meridian_problem()
    built = build(problem)
    solver, status = solve_built(built)
    schedule = schedule_from(problem, built, solver)
    assert len(schedule.placements) == SLOT_COUNT * len(problem.classes())
    assert ClassRef(7, "C") in {p.class_ref for p in schedule.placements}
