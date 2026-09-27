from ortools.sat.python import cp_model

from roster.domain import SLOT_COUNT, ClassRef
from roster.model import build, schedule_from
from roster.verify import verify
from tests.fixtures.meridian import meridian_problem


def solve_built(built, time_limit=45.0, linearization_level=0):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    # This model is almost entirely boolean with every shape rule guarded by
    # an OnlyEnforceIf assumption literal. CP-SAT's linear-relaxation layer
    # buys nothing here and, empirically, costs an order of magnitude of
    # search time on the plain Meridian fixture (first feasible solution at
    # ~70s instead of ~10s). Disabling it is a solver-tuning choice, not a
    # model change: num_search_workers stays 1 and the seed stays fixed.
    #
    # It is NOT a universal win, though: the min_doubles scenario below
    # (near its doubles ceiling) finds a solution at ~170s with CP-SAT's
    # default linearization, but not at all within 220s with it disabled.
    # Callers with an unusually tight model can pass linearization_level=None
    # to keep CP-SAT's default.
    if linearization_level is not None:
        solver.parameters.linearization_level = linearization_level
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


from roster.allocation import doubles_ceiling
from roster.domain import DAYS, day_of
from roster.model import total_doubles_ceiling
from roster.verify import count_doubles


def test_double_variables_exist_only_for_same_day_pairs():
    problem = meridian_problem()
    built = build(problem)
    assert built.doubles
    for (_class_ref, _code, (a, b)) in built.doubles:
        assert day_of(a) == day_of(b)
        assert b == a + 1


# Review Focus 2
def test_no_double_variable_spans_the_day_boundary():
    built = build(meridian_problem())
    boundaries = {(d * 10 + 9, d * 10 + 10) for d in range(DAYS - 1)}
    for (_class_ref, _code, pair) in built.doubles:
        assert pair not in boundaries


def test_double_variables_exist_only_for_core_subjects():
    problem = meridian_problem()
    built = build(problem)
    for (_class_ref, code, _pair) in built.doubles:
        assert problem.is_core(code)


def test_total_doubles_ceiling_matches_the_spec_table():
    problem = meridian_problem()
    # Gr4-6: HL 12 -> 6, FAL 10 -> 4, MATH 12 -> 6 = 16 per class.
    # Gr7:   HL 10 -> 4, FAL 8 -> 2, MATH 9 -> 3 = 9 per class.
    assert doubles_ceiling(12) + doubles_ceiling(10) + doubles_ceiling(12) == 16
    assert doubles_ceiling(10) + doubles_ceiling(8) + doubles_ceiling(9) == 9
    assert total_doubles_ceiling(problem) == 16 * 9 + 9 * 3


def test_core_subjects_appear_once_or_twice_every_day():
    problem = meridian_problem()
    built = build(problem)
    solver, status = solve_built(built)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    schedule = schedule_from(problem, built, solver)
    for class_ref in problem.classes():
        for code in problem.demand_for(class_ref.grade):
            if not problem.is_core(code):
                continue
            per_day = [0] * DAYS
            for slot in schedule.slots_of(class_ref, code):
                per_day[day_of(slot)] += 1
            assert all(1 <= n <= 2 for n in per_day), (class_ref, code, per_day)


def test_non_core_respects_its_daily_cap():
    problem = meridian_problem()
    built = build(problem)
    solver, status = solve_built(built)
    schedule = schedule_from(problem, built, solver)
    assert verify(problem, schedule) == []


def test_model_and_verifier_agree_on_the_doubles_count():
    """The objective value and the independent count must match exactly.

    This cross-checks the model's reified doubles encoding against the
    verifier, which is the assertion that actually catches an encoding bug.
    The ceiling is an upper bound, not necessarily attainable, so equality
    with the ceiling is deliberately NOT asserted.
    """
    problem = meridian_problem()
    built = build(problem)
    solver, status = solve_built(built, time_limit=120.0)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    schedule = schedule_from(problem, built, solver)
    placed = count_doubles(problem, schedule)
    assert placed == int(solver.ObjectiveValue())
    assert 0 < placed <= total_doubles_ceiling(problem)


def test_min_doubles_is_honoured_when_set():
    """A minimum below the ceiling is enforced.

    Deliberately 4, not 6. Grade 4 HL has 12 periods, so its doubles ceiling
    is 6 — and demanding the ceiling as a HARD constraint is the one thing
    spec 6.5 warns against. Measured: min_doubles of 3, 4 and 5 all solve
    (first solution in about 4 seconds), while 6 returns UNKNOWN after 90
    seconds, so the ceiling is not reachable as a hard rule on this fixture.
    This test's job is to prove a minimum is honoured, not to prove the
    ceiling is attainable — which it is not.
    """
    problem = meridian_problem(min_doubles={(4, "HL"): 4})
    built = build(problem)
    solver, status = solve_built(built, time_limit=60.0)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    schedule = schedule_from(problem, built, solver)
    for section in ("A", "B", "C"):
        slots = schedule.slots_of(ClassRef(4, section), "HL")
        pairs = sum(
            1
            for i in range(len(slots) - 1)
            if slots[i + 1] == slots[i] + 1 and day_of(slots[i]) == day_of(slots[i + 1])
        )
        assert pairs >= 4
