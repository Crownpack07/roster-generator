import random

import pytest

from roster.domain import PERIODS_PER_DAY
from roster.io import problem_from_dict, problem_to_dict
from roster.solve import SolveResult, SolveStatus, solve
from roster.verify import verify
from tests.fixtures.meridian import meridian_problem

# Every test in this module drives the CP-SAT solver, so each costs its
# full time budget. Excluded from the default `pytest` run — see the
# markers config in pyproject.toml. Run with `pytest -m solver`.
pytestmark = pytest.mark.solver


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


def _reordered(problem, seed):
    """The same school with its lists in a different order.

    Seed None sorts the way the store returns them (subjects and curriculum
    by code, teachers by name); an int shuffles.
    """
    d = problem_to_dict(problem)
    if seed is None:
        d["subjects"].sort(key=lambda s: s["code"])
        d["teachers"].sort(key=lambda t: t["name"])
        for key in ("caps", "optional"):
            d["scenario"][key].sort(key=lambda e: (e["grade"], e["subject"]))
    else:
        rng = random.Random(seed)
        for key in ("subjects", "teachers", "blocks"):
            rng.shuffle(d[key])
        for key in ("caps", "optional"):
            rng.shuffle(d["scenario"][key])
    return problem_from_dict(d)


@pytest.mark.parametrize("seed", [None, 1, 3])
def test_the_real_school_solves_in_any_input_order(seed):
    """Input order used to decide whether the school solved at all: the order
    the store returns failed inside 60s where the fixture's order took 10s."""
    problem = _reordered(meridian_problem(), seed)
    result = solve(problem, **SOLVE_KWARGS)
    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)
    assert verify(problem, result.schedule) == []


def test_a_perfect_timetable_is_proven_optimal_without_using_the_budget():
    """Every double placed is provably the best answer, so stop there.

    Runs with the production default of one worker per core. Reaching all
    171 doubles takes CP-SAT's wider portfolio: measured, 14 cores proved it
    in 7-20s, while two workers reached 168-170 in 20s without proving
    it. On a machine with few cores this test can fail without the
    solver being wrong.
    """
    result = solve(meridian_problem(), seed=1, time_limit_s=60.0)
    assert result.status is SolveStatus.OPTIMAL
    assert result.doubles_placed == result.doubles_ceiling
    assert result.wall_seconds < 30.0


def test_an_infeasible_school_still_gets_a_conflict_report():
    problem = meridian_problem(min_doubles={(4, "FAL"): 6})
    result = solve(problem, run_preflight=False, **SOLVE_KWARGS)
    assert result.status is SolveStatus.INFEASIBLE
    assert result.conflict is not None
    assert result.conflict.rule_groups


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
    for result in (a, b):
        assert verify(problem, result.schedule) == []


@pytest.mark.parametrize(
    "teacher, blocked",
    [
        ("Shane", frozenset({PERIODS_PER_DAY, PERIODS_PER_DAY + 1})),
        # Once the case that proved the solver fragile: blocking Karin's
        # slots returned UNKNOWN where blocking Shane's solved, despite
        # identical loads. Both solve in under a second since the search
        # model dropped its diagnosis guards.
        ("Karin", frozenset({0, 1})),
    ],
)
def test_blocked_slots_are_respected(teacher, blocked):
    problem = meridian_problem(blocked={teacher: blocked})
    result = solve(problem, **SOLVE_KWARGS)
    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)
    assert verify(problem, result.schedule) == []
    for placement in result.schedule.placements:
        block = problem.block_for(placement.class_ref, placement.subject_code)
        if block is not None and block.teacher_id == teacher:
            assert placement.slot not in blocked


def test_sepedi_on_with_an_override_is_accepted():
    """The CAPS-override path reaches the solver and reports its deviation.

    Grade 4 fits 61 periods into 60 only by shaving two CAPS subjects. The
    override path must clear pre-flight, report its deviation, and solve.
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
    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)
    assert verify(problem, result.schedule) == []
