"""CAPS-compliant school timetable solver."""

from roster.domain import (
    DAYS,
    PERIODS_PER_DAY,
    SLOT_COUNT,
    Block,
    ClassRef,
    Placement,
    Schedule,
    Subject,
    Teacher,
)
from roster.preflight import Finding, preflight
from roster.problem import Problem
from roster.solve import SolveResult, SolveStatus, solve
from roster.verify import Violation, count_doubles, verify

# The re-exported solve, preflight and verify FUNCTIONS shadow their
# submodules as attributes of `roster`: after this import, `roster.solve` is
# the function, not the module. So reach the modules with
# `from roster.solve import X` or `importlib.import_module("roster.solve")`;
# never `import roster.solve as m` or `monkeypatch.setattr("roster.solve.X",
# ...)`, which resolve through the attribute and get the function.
__all__ = [
    "DAYS",
    "PERIODS_PER_DAY",
    "SLOT_COUNT",
    "Block",
    "ClassRef",
    "Finding",
    "Placement",
    "Problem",
    "Schedule",
    "SolveResult",
    "SolveStatus",
    "Subject",
    "Teacher",
    "Violation",
    "count_doubles",
    "preflight",
    "solve",
    "verify",
]
