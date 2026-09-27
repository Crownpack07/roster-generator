"""Orchestration: pre-flight, build, solve, map status, assemble the result."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

from ortools.sat.python import cp_model

from roster.diagnose import ConflictReport, explain
from roster.domain import Schedule
from roster.model import build, schedule_from, total_doubles_ceiling
from roster.preflight import Finding, has_errors, preflight
from roster.problem import Problem
from roster.verify import count_doubles


class SolveStatus(StrEnum):
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
    cp_model.MODEL_INVALID: SolveStatus.UNKNOWN,
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
    findings = preflight(problem) if run_preflight else []
    ceiling = total_doubles_ceiling(problem)

    if run_preflight and has_errors(findings):
        return SolveResult(
            status=SolveStatus.BLOCKED,
            doubles_ceiling=ceiling,
            findings=findings,
        )

    built = build(problem)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    if seed is not None:
        solver.parameters.random_seed = seed
    if workers is not None:
        solver.parameters.num_search_workers = workers

    # Time-limit/linearization decision (measured on the real Meridian
    # fixture, seed 1, single worker, 100s cap):
    #
    #   scenario                       linearization=0    CP-SAT default
    #   baseline, no min_doubles       FEASIBLE at 10.1s   FEASIBLE at 68.6s
    #   min_doubles={(4,"HL"): 4}      FEASIBLE at 3.8s    FEASIBLE at 68.8s
    #   min_doubles={(4,"HL"): 6}      UNKNOWN, never      UNKNOWN, never
    #
    # This model is almost entirely boolean, with every rule group guarded by
    # an OnlyEnforceIf assumption literal, so CP-SAT's linear-relaxation
    # layer buys nothing and, empirically, costs a 7-18x slowdown to first
    # solution on every solvable instance measured. With CP-SAT's default
    # settings the real school needs ~69s to reach a feasible timetable,
    # which would blow straight through the old 30s default and hand a real
    # administrator UNKNOWN on the primary use case.
    #
    # There is one counter-claim on record: an earlier note that on the
    # min_doubles=6 instance (near/at the doubles ceiling) CP-SAT's default
    # linearization found a solution at ~170s where linearization=0 did not
    # within ~220s. That could not be reproduced within a 100s cap here —
    # both settings return UNKNOWN on that instance, i.e. neither setting
    # wins it, and that instance is one already established as unreachable
    # and removed from the test suite. It is not evidence against disabling
    # linearization for every instance this project actually ships.
    #
    # So: disable it unconditionally, the same choice tests/test_model.py
    # already made for its own solver helper. This keeps production and
    # tests coherent instead of tuned differently for no documented reason.
    # The 30s default `time_limit_s` above is then a >3x margin over the
    # slowest measured first-solution time (10.1s) with this setting, so the
    # default configuration should not return UNKNOWN on a solvable school.
    solver.parameters.linearization_level = 0

    started = time.monotonic()
    raw = solver.Solve(built.model)
    elapsed = time.monotonic() - started
    status = _STATUS_MAP.get(raw, SolveStatus.UNKNOWN)

    if status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE):
        schedule = schedule_from(problem, built, solver)
        return SolveResult(
            status=status,
            schedule=schedule,
            doubles_placed=count_doubles(problem, schedule),
            doubles_ceiling=ceiling,
            wall_seconds=elapsed,
            findings=findings,
        )

    conflict = None
    if status is SolveStatus.INFEASIBLE:
        conflict = explain(problem, built, solver)

    return SolveResult(
        status=status,
        doubles_ceiling=ceiling,
        wall_seconds=elapsed,
        findings=findings,
        conflict=conflict,
    )
