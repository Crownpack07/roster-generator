from ortools.sat.python import cp_model

from roster.diagnose import RULE_SENTENCES, ConflictReport, explain, remedies_for
from roster.model import ALL_RULES, RULE_CORE_DAILY, RULE_MIN_DOUBLES, build
from roster.solve import SolveStatus, solve
from tests.fixtures.meridian import meridian_problem


def test_every_rule_group_has_an_english_sentence():
    for rule in ALL_RULES:
        assert rule in RULE_SENTENCES
        assert RULE_SENTENCES[rule].endswith(".")


def test_explain_names_the_conflicting_rule_groups():
    problem = meridian_problem(min_doubles={(4, "FAL"): 6})
    built = build(problem)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    status = solver.Solve(built.model)
    assert status == cp_model.INFEASIBLE

    report = explain(problem, built, solver)
    assert isinstance(report, ConflictReport)
    assert report.rule_groups
    assert set(report.rule_groups) <= set(ALL_RULES)


def test_explain_produces_one_sentence_per_rule_group():
    problem = meridian_problem(min_doubles={(4, "FAL"): 6})
    built = build(problem)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    solver.Solve(built.model)
    report = explain(problem, built, solver)
    assert len(report.sentences) == len(report.rule_groups)
    for sentence in report.sentences:
        assert sentence == sentence.strip()
        assert sentence


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


def test_explain_returns_empty_report_for_a_feasible_model():
    problem = meridian_problem()
    built = build(problem)
    solver = cp_model.CpSolver()
    # 30s, not 120s: CP-SAT spends its whole budget proving optimality even
    # after it has an answer, and this solve only needs to reach a feasible
    # model so explain() has something non-infeasible to look at. Measured
    # first solution on this fixture is ~10.5s with linearization disabled.
    solver.parameters.max_time_in_seconds = 30.0
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    solver.parameters.linearization_level = 0
    solver.Solve(built.model)
    report = explain(problem, built, solver)
    assert report.rule_groups == ()
    assert report.sentences == ()
