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
