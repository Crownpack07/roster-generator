"""Solver settings and the solve() orchestration, without a real search.

Each test here either inspects parameters or stands a stub in for CP-SAT's
Solve, so the whole module runs in the fast suite.
"""

import importlib
import os
from types import SimpleNamespace

import pytest
from ortools.sat.python import cp_model

from roster.model import BuiltModel
from roster.solve import MAX_DEFAULT_WORKERS, SolveStatus, _solver, solve
from tests.fixtures.meridian import meridian_problem

# importlib, not `import roster.solve`: the package re-exports the solve
# FUNCTION under that name (see roster/__init__.py).
solve_module = importlib.import_module("roster.solve")


@pytest.mark.parametrize("workers", [None, 1, 3, 4, 8])
def test_the_solver_never_runs_on_fewer_than_four_workers(workers):
    """Measured: one worker finds no timetable in 30s on any school tried;
    two or three find one in 0.3s but cannot prove an infeasible school
    infeasible; four do both. See the note in roster/solve.py."""
    solver = _solver(30.0, seed=None, workers=workers)
    assert solver.parameters.num_search_workers >= 4
    if workers is not None and workers >= 4:
        assert solver.parameters.num_search_workers == workers


@pytest.mark.parametrize("cores, expected", [(2, 4), (6, 6), (64, 8)])
def test_the_default_follows_usable_cores_capped_at_eight(
    monkeypatch, cores, expected
):
    # process_cpu_count respects affinity and cgroups; cpu_count does not.
    monkeypatch.setattr(os, "process_cpu_count", lambda: cores, raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 999)
    solver = _solver(30.0, seed=None, workers=None)
    assert solver.parameters.num_search_workers == expected
    assert MAX_DEFAULT_WORKERS == 8


def test_the_default_falls_back_to_cpu_count_before_python_3_13(monkeypatch):
    monkeypatch.delattr(os, "process_cpu_count", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 6)
    assert _solver(30.0, seed=None, workers=None).parameters.num_search_workers == 6


def test_an_explicit_worker_count_above_the_default_cap_is_honoured():
    assert _solver(30.0, seed=None, workers=16).parameters.num_search_workers == 16


class _StubSolver:
    """Answers Solve with a fixed status and advances a fake clock."""

    def __init__(self, status, clock, seconds):
        self.status, self.clock, self.seconds = status, clock, seconds

    def Solve(self, model):
        self.clock[0] += self.seconds
        return self.status


def _stub_solves(monkeypatch, *statuses, seconds=5.0):
    clock = [0.0]
    stubs = iter(_StubSolver(s, clock, seconds) for s in statuses)
    monkeypatch.setattr(solve_module, "_solver", lambda *a, **k: next(stubs))
    monkeypatch.setattr(
        solve_module, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )


def test_a_diagnosis_that_times_out_still_says_the_school_is_impossible(
    monkeypatch,
):
    # The search proves INFEASIBLE; the guarded diagnosis re-solve then runs
    # out of time.
    _stub_solves(monkeypatch, cp_model.INFEASIBLE, cp_model.UNKNOWN)
    result = solve(meridian_problem(), run_preflight=False)

    assert result.status is SolveStatus.INFEASIBLE
    report = result.conflict
    assert report is not None
    assert report.rule_groups == ()
    text = " ".join(report.sentences)
    assert "impossible" in text and "time limit" in text
    assert "longer" in text
    assert report.remedies


def test_wall_seconds_covers_the_search_and_the_diagnosis(monkeypatch):
    _stub_solves(monkeypatch, cp_model.INFEASIBLE, cp_model.UNKNOWN)
    result = solve(meridian_problem(), run_preflight=False)
    assert result.wall_seconds == 10.0


def test_an_invalid_model_raises_instead_of_reporting_unknown(monkeypatch):
    invalid = cp_model.CpModel()
    invalid.NewIntVar(5, 1, "backwards")  # an empty domain
    monkeypatch.setattr(
        solve_module, "build", lambda problem, **kw: BuiltModel(model=invalid)
    )
    with pytest.raises(RuntimeError, match="backwards"):
        solve(meridian_problem(), run_preflight=False)


def test_solve_status_documents_every_value():
    doc = SolveStatus.__doc__ or ""
    for status in SolveStatus:
        assert status.value in doc
    assert "never" in doc.lower()
