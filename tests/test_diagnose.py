from dataclasses import replace
from types import SimpleNamespace

import pytest

from ortools.sat.python import cp_model

from roster.diagnose import RULE_SENTENCES, ConflictReport, explain, remedies_for
from roster.model import (
    ALL_RULES,
    RULE_CORE_DAILY,
    RULE_MIN_DOUBLES,
    RULE_PERIOD_COUNTS,
    RULE_SPREAD,
    RULE_TEACHER_CLASH,
    build,
)
from roster.solve import SolveStatus, solve
from tests.fixtures.meridian import meridian_problem

# Tests marked `solver` drive CP-SAT and cost their time budget; they are
# excluded from the default `pytest` run (see pyproject.toml). The rest read
# remedies or a stub solver and run in the fast suite.


def test_every_rule_group_has_an_english_sentence():
    for rule in ALL_RULES:
        assert rule in RULE_SENTENCES
        assert RULE_SENTENCES[rule].endswith(".")


@pytest.mark.solver
def test_explain_names_the_conflicting_rule_groups():
    problem = meridian_problem(min_doubles={(4, "FAL"): 6})
    built = build(problem, guarded=True)
    solver = cp_model.CpSolver()
    # A bound, so a regression fails instead of hanging. Linearization off,
    # as solve() runs it: measured, that proves this guarded model
    # infeasible in under a second, where with it on 60s is not enough.
    solver.parameters.max_time_in_seconds = 60.0
    solver.parameters.linearization_level = 0
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    status = solver.Solve(built.model)
    assert status == cp_model.INFEASIBLE

    report = explain(problem, built, solver)
    assert isinstance(report, ConflictReport)
    assert report.rule_groups
    assert set(report.rule_groups) <= set(ALL_RULES)


@pytest.mark.solver
def test_explain_produces_one_sentence_per_rule_group():
    problem = meridian_problem(min_doubles={(4, "FAL"): 6})
    built = build(problem, guarded=True)
    solver = cp_model.CpSolver()
    # A bound, so a regression fails instead of hanging. Linearization off,
    # as solve() runs it: measured, that proves this guarded model
    # infeasible in under a second, where with it on 60s is not enough.
    solver.parameters.max_time_in_seconds = 60.0
    solver.parameters.linearization_level = 0
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    solver.Solve(built.model)
    report = explain(problem, built, solver)
    # One sentence per rule group, plus one extra leading "degenerate core"
    # note when the core could not be narrowed below every rule group -
    # the worst case the model's coarse, one-literal-per-category
    # assumptions permit.
    expected = len(report.rule_groups)
    if len(report.rule_groups) == len(ALL_RULES):
        expected += 1
    assert len(report.sentences) == expected
    for sentence in report.sentences:
        assert sentence == sentence.strip()
        assert sentence


@pytest.mark.solver
def test_explain_offers_at_least_one_remedy():
    problem = meridian_problem(min_doubles={(4, "FAL"): 6})
    result = solve(
        problem, run_preflight=False, seed=1, workers=1, time_limit_s=30.0
    )
    assert result.status is SolveStatus.INFEASIBLE
    assert result.conflict is not None
    assert result.conflict.remedies


def test_min_doubles_conflict_suggests_relaxing_min_doubles():
    remedies = remedies_for(
        meridian_problem(min_doubles={(4, "FAL"): 6}),
        (RULE_MIN_DOUBLES, RULE_CORE_DAILY),
    )
    joined = " ".join(remedies)
    assert "minimum" in joined.lower()


def test_teacher_clash_conflict_suggests_reassignment_with_capacity():
    from roster.model import RULE_TEACHER_CLASH

    remedies = remedies_for(meridian_problem(), (RULE_TEACHER_CLASH,))
    joined = " ".join(remedies)
    assert "reassign" in joined.lower()
    # Names at least one teacher who has spare capacity.
    assert any(name in joined for name in ("Shane", "Corlie", "Tanya"))


@pytest.mark.solver
def test_explain_returns_empty_report_for_a_feasible_model():
    problem = meridian_problem()
    built = build(problem, guarded=True)
    solver = cp_model.CpSolver()
    # 30s, not 120s: CP-SAT spends its whole budget proving optimality even
    # after it has an answer, and this solve only needs to reach a feasible
    # model so explain() has something non-infeasible to look at. Measured
    # first solution of this GUARDED model on one worker, linearization off:
    # ~10.4s (2026-10-01). The unguarded model solve() searches since
    # 6dcdd52 finds one in about 0.3s; this figure is for the guards.
    solver.parameters.max_time_in_seconds = 30.0
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    solver.parameters.linearization_level = 0
    solver.Solve(built.model)
    report = explain(problem, built, solver)
    assert report.rule_groups == ()
    assert report.sentences == ()


# --- remedies whose precondition is absent are skipped (M6) -----------------
def test_no_double_minimum_remedy_when_none_is_set():
    remedies = remedies_for(meridian_problem(), (RULE_MIN_DOUBLES,))
    assert not any("minimum" in r.lower() for r in remedies)


def _all_subjects(problem, *, core):
    problem.subjects = {
        c: replace(s, is_core=core) for c, s in problem.subjects.items()
    }
    return problem


def test_no_core_daily_remedy_for_a_school_without_core_subjects():
    problem = _all_subjects(meridian_problem(), core=False)
    remedies = remedies_for(problem, (RULE_CORE_DAILY, RULE_SPREAD))
    assert not any("miss a day" in r for r in remedies)
    assert any("non-core" in r for r in remedies)


def test_no_spread_remedy_for_a_school_without_non_core_subjects():
    problem = _all_subjects(meridian_problem(), core=True)
    remedies = remedies_for(problem, (RULE_CORE_DAILY, RULE_SPREAD))
    assert any("miss a day" in r for r in remedies)
    assert not any("non-core" in r for r in remedies)


def test_no_turn_optional_off_remedy_when_none_is_on():
    remedies = remedies_for(
        meridian_problem(enabled_optional=()), (RULE_PERIOD_COUNTS,)
    )
    assert remedies
    assert not any("optional" in r for r in remedies)
    on = remedies_for(meridian_problem(), (RULE_PERIOD_COUNTS,))
    assert any("optional" in r for r in on)


def test_no_reassignment_remedy_with_a_single_teacher():
    problem = meridian_problem()
    problem.teachers = {"Karin": problem.teachers["Karin"]}
    problem.blocks = problem.blocks_of("Karin")
    remedies = remedies_for(problem, (RULE_TEACHER_CLASH,))
    assert not any("reassign" in r.lower() for r in remedies)


# --- explain() with a narrowed core, no CP-SAT solve (#24) -------------------
def test_explain_a_narrowed_core_gives_one_sentence_per_group():
    built = SimpleNamespace(
        assumptions={
            rule: SimpleNamespace(Index=lambda i=i: 100 + i)
            for i, rule in enumerate(ALL_RULES)
        }
    )
    picked = (RULE_CORE_DAILY, RULE_MIN_DOUBLES)
    solver = SimpleNamespace(
        SufficientAssumptionsForInfeasibility=lambda: [
            100 + ALL_RULES.index(r) for r in picked
        ]
    )
    report = explain(
        meridian_problem(min_doubles={(4, "FAL"): 6}), built, solver
    )
    assert report.rule_groups == picked
    # No leading "could not narrow" note: exactly one sentence per group.
    assert report.sentences == tuple(RULE_SENTENCES[r] for r in picked)
    assert report.remedies
