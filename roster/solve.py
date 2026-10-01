"""Orchestration: pre-flight, build, solve, map status, assemble the result."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import StrEnum

from ortools.sat.python import cp_model

from roster.diagnose import ConflictReport, explain, undiagnosed_report
from roster.domain import Schedule
from roster.model import build, schedule_from, total_doubles_ceiling
from roster.preflight import Finding, has_errors, preflight
from roster.problem import Problem
from roster.verify import count_doubles

MIN_WORKERS = 4
MAX_DEFAULT_WORKERS = 8


class SolveStatus(StrEnum):
    """What a solve ended in. Never merge two of these.

    - optimal: a timetable, proven to place every achievable double.
    - feasible: a timetable, not proven to be the best.
    - infeasible: proven impossible. No timetable satisfies the rules.
    - unknown: ran out of time without proving either way. Never report it
      as "impossible": a longer limit may find a timetable.
    - blocked: pre-flight found errors, so the solver never ran.
    """

    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


@dataclass
class SolveResult:
    status: SolveStatus
    schedule: Schedule | None = None
    doubles_placed: int = 0
    doubles_ceiling: int = 0
    wall_seconds: float = 0.0
    findings: list[Finding] = field(default_factory=list)
    conflict: ConflictReport | None = None


_STATUS_MAP = {
    cp_model.OPTIMAL: SolveStatus.OPTIMAL,
    cp_model.FEASIBLE: SolveStatus.FEASIBLE,
    cp_model.INFEASIBLE: SolveStatus.INFEASIBLE,
    cp_model.UNKNOWN: SolveStatus.UNKNOWN,
}


def solve(
    problem: Problem,
    *,
    time_limit_s: float = 30.0,
    seed: int | None = None,
    workers: int | None = None,
    run_preflight: bool = True,
) -> SolveResult:
    """Pre-flight, then search, then explain an infeasible answer.

    An infeasible result runs a second, guarded solve to name the rules in
    conflict, which has its own `time_limit_s`: such a result can take up to
    twice the limit, and `wall_seconds` covers both solves.

    Raises RuntimeError when CP-SAT rejects the model itself: that is a bug
    in the model, never an answer about the school.
    """
    findings = preflight(problem) if run_preflight else []
    ceiling = total_doubles_ceiling(problem)

    if run_preflight and has_errors(findings):
        return SolveResult(
            status=SolveStatus.BLOCKED,
            doubles_ceiling=ceiling,
            findings=findings,
        )

    built = build(problem)
    solver = _solver(time_limit_s, seed, workers)

    started = time.monotonic()
    raw = solver.Solve(built.model)
    _raise_if_invalid(raw, built.model)
    status = _STATUS_MAP.get(raw, SolveStatus.UNKNOWN)

    if status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE):
        schedule = schedule_from(problem, built, solver)
        return SolveResult(
            status=status,
            schedule=schedule,
            doubles_placed=count_doubles(problem, schedule),
            doubles_ceiling=ceiling,
            wall_seconds=time.monotonic() - started,
            findings=findings,
        )

    conflict = None
    if status is SolveStatus.INFEASIBLE:
        conflict = _explain_infeasible(problem, time_limit_s, seed, workers)

    return SolveResult(
        status=status,
        doubles_ceiling=ceiling,
        wall_seconds=time.monotonic() - started,
        findings=findings,
        conflict=conflict,
    )


def _raise_if_invalid(raw, model: cp_model.CpModel) -> None:
    """An invalid model is a bug in the model, never an answer."""
    if raw == cp_model.MODEL_INVALID:
        raise RuntimeError(
            f"CP-SAT rejected the model as invalid: {model.Validate()}"
        )


def _explain_infeasible(
    problem: Problem,
    time_limit_s: float,
    seed: int | None,
    workers: int | None,
) -> ConflictReport:
    """Re-solve with every rule group guarded, to read which ones conflict.

    Only an infeasible answer pays for the guarded model: its guards are what
    make it slow, and a feasible solve has nothing to explain. When the
    re-solve runs out of time the school is still proven impossible; the
    report says so rather than coming back empty.
    """
    built = build(problem, guarded=True)
    solver = _solver(time_limit_s, seed, workers)
    raw = solver.Solve(built.model)
    _raise_if_invalid(raw, built.model)
    if raw != cp_model.INFEASIBLE:
        return undiagnosed_report(problem)
    return explain(problem, built, solver)


def _solver(
    time_limit_s: float, seed: int | None, workers: int | None
) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    if seed is not None:
        solver.parameters.random_seed = seed
    # Never fewer than four. CP-SAT fills worker slots in a fixed order.
    # One worker runs only the tree search: no timetable in 30s on any school
    # measured. Two or three add Feasibility Jump, which finds one in 0.3s,
    # but then cannot prove an infeasible school infeasible within 20s. Four
    # does both: 0.3s to a timetable, 1.2-2.3s to a proof, across seeds.
    # Feasibility Jump needs milliseconds of CPU, so four threads sharing
    # fewer cores still work, only slower.
    # The default is the cores this process may use (process_cpu_count
    # honours affinity and cgroups; it is 3.13+, so fall back), capped at 8
    # so a big host is not monopolised. An explicit count is honoured.
    usable = getattr(os, "process_cpu_count", os.cpu_count)() or 1
    solver.parameters.num_search_workers = max(
        MIN_WORKERS, workers or min(usable, MAX_DEFAULT_WORKERS)
    )

    # Linear relaxation off. Measured on the old guarded model it cost a
    # 7-18x slowdown to first solution (10s vs 69s on the real school). Every
    # measurement of the current model was taken with it off, including the
    # sub-second first solutions, so it stays off; it has not been
    # re-measured on the unguarded model.
    solver.parameters.linearization_level = 0
    return solver

