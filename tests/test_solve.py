import pytest

from roster.domain import PERIODS_PER_DAY
from roster.solve import SolveResult, SolveStatus, solve
from roster.verify import verify
from tests.fixtures.meridian import meridian_problem

SOLVE_KWARGS = {"seed": 1, "workers": 1, "time_limit_s": 30.0}


def test_the_four_statuses_are_distinct_values():
    values = {
        SolveStatus.OPTIMAL,
        SolveStatus.FEASIBLE,
        SolveStatus.INFEASIBLE,
        SolveStatus.UNKNOWN,
    }
    assert len(values) == 4
    assert SolveStatus.INFEASIBLE != SolveStatus.UNKNOWN


def test_real_school_solves_and_verifies_clean():
    problem = meridian_problem()
    result = solve(problem, **SOLVE_KWARGS)
    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE), (
        result.status,
        [f.message for f in result.findings],
    )
    assert result.schedule is not None
    assert verify(problem, result.schedule) == []


def test_doubles_ceiling_matches_the_spec_table():
    # 16 per class in grades 4-6 (nine classes), 9 per class in grade 7.
    result = solve(meridian_problem(), **SOLVE_KWARGS)
    assert result.doubles_ceiling == 16 * 9 + 9 * 3
    assert 0 < result.doubles_placed <= result.doubles_ceiling


def test_result_reports_wall_time():
    result = solve(meridian_problem(), **SOLVE_KWARGS)
    assert result.wall_seconds >= 0.0


def test_warnings_survive_a_successful_solve():
    result = solve(meridian_problem(), **SOLVE_KWARGS)
    assert any(f.severity == "warning" for f in result.findings)
    assert all(f.severity != "error" for f in result.findings)


def test_preflight_errors_block_the_solver_without_running_it():
    problem = meridian_problem(enabled_optional=("BIB", "SEP", "SPT"))
    result = solve(problem, **SOLVE_KWARGS)
    assert result.status is SolveStatus.BLOCKED
    assert result.schedule is None
    assert any(f.code == "class_total" for f in result.findings)
    assert result.wall_seconds == 0.0


def test_blocked_is_not_reported_as_infeasible():
    problem = meridian_problem(enabled_optional=("BIB", "SEP", "SPT"))
    result = solve(problem, **SOLVE_KWARGS)
    assert result.status is not SolveStatus.INFEASIBLE
    assert result.status is not SolveStatus.UNKNOWN


def test_structurally_infeasible_problem_is_proven_infeasible():
    # Force min_doubles above the achievable ceiling for one grade-4 subject.
    problem = meridian_problem(min_doubles={(4, "FAL"): 6})
    result = solve(problem, run_preflight=False, **SOLVE_KWARGS)
    assert result.status is SolveStatus.INFEASIBLE
    assert result.schedule is None


def test_a_tiny_time_limit_reports_unknown_not_infeasible():
    problem = meridian_problem()
    result = solve(problem, time_limit_s=0.001, seed=1, workers=1)
    assert result.status in (
        SolveStatus.UNKNOWN,
        SolveStatus.FEASIBLE,
        SolveStatus.OPTIMAL,
    )
    assert result.status is not SolveStatus.INFEASIBLE


def test_repeated_solves_agree_on_properties_not_on_the_exact_schedule():
    """Two runs with the same seed may differ, and that is expected.

    Spec 14 originally claimed fixing the seed and forcing one worker makes
    runs reproducible. Measured: it does not. A wall-clock budget stops the
    search wherever it happens to be when the clock expires, so identical
    seeds legitimately return different schedules. Reproducibility would need
    the search to run to completion, which on this model it does not. So
    assert properties, never an exact schedule.
    """
    problem = meridian_problem()
    a = solve(problem, **SOLVE_KWARGS)
    b = solve(problem, **SOLVE_KWARGS)
    assert a.status == b.status
    assert a.doubles_ceiling == b.doubles_ceiling
    if a.schedule is None and b.schedule is None:
        pytest.skip(
            f"neither run found a schedule within "
            f"{SOLVE_KWARGS['time_limit_s']}s (status {a.status}); the status "
            f"and ceiling agreement above was still asserted"
        )
    for result in (a, b):
        if result.schedule is not None:
            assert verify(problem, result.schedule) == []


def test_blocked_slots_are_respected_when_a_timetable_is_found():
    """Any timetable the solver returns honours blocked slots.

    Asserted conditionally, on purpose. Blocking slots can make the whole
    problem unsolvable inside the time limit: measured, blocking two of
    Petra's slots returns UNKNOWN at 200s, and blocking Karin's fails where
    blocking Shane's succeeds, despite identical loads and both holding only
    non-core subjects. Requiring a solve here would be asserting solver luck.
    The unconditional guarantee lives in
    tests/test_model.py::test_blocked_slots_are_left_empty_for_that_teacher.
    """
    blocked = frozenset({PERIODS_PER_DAY, PERIODS_PER_DAY + 1})
    problem = meridian_problem(blocked={"Shane": blocked})
    result = solve(problem, **SOLVE_KWARGS)
    assert result.status is not SolveStatus.BLOCKED
    assert result.status is not SolveStatus.INFEASIBLE
    if result.schedule is None:
        pytest.skip(
            f"no schedule found within {SOLVE_KWARGS['time_limit_s']}s "
            f"(status {result.status}); the blocked-slot guarantee itself is "
            f"asserted unconditionally in tests/test_model.py::"
            f"test_blocked_slots_are_left_empty_for_that_teacher"
        )
    assert verify(problem, result.schedule) == []
    for placement in result.schedule.placements:
        block = problem.block_for(placement.class_ref, placement.subject_code)
        if block is not None and block.teacher_id == "Shane":
            assert placement.slot not in blocked


def test_sepedi_on_with_an_override_is_accepted():
    """The CAPS-override path reaches the solver and reports its deviation.

    Grade 4 fits 61 periods into 60 only by shaving two CAPS subjects. What
    this pins is that the override path yields a well-formed problem that
    clears pre-flight and is reported as deviating — not that a timetable is
    found, which measurement shows may not happen inside the limit.
    """
    problem = meridian_problem(
        enabled_optional=("BIB", "SEP", "SPT"),
        overrides={(4, "SS"): 5, (4, "LS"): 5},
    )
    result = solve(problem, **SOLVE_KWARGS)
    assert result.status is not SolveStatus.BLOCKED, [
        f.message for f in result.findings if f.severity == "error"
    ]
    assert result.status is not SolveStatus.INFEASIBLE
    assert any(f.code == "caps_deviation" for f in result.findings)
    if result.schedule is None:
        pytest.skip(
            f"no schedule found within {SOLVE_KWARGS['time_limit_s']}s "
            f"(status {result.status}); the override path reaching the solver "
            f"and reporting its deviation was still asserted"
        )
    assert verify(problem, result.schedule) == []
