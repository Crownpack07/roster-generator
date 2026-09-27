"""Layer 2: translate an UNSAT core into English. Filled out in Task 10."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConflictReport:
    rule_groups: tuple[str, ...] = ()
    sentences: tuple[str, ...] = ()
    remedies: tuple[str, ...] = ()


def explain(problem, built, solver) -> ConflictReport:
    return ConflictReport()
