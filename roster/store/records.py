"""What repositories return: documents decoded into plain Python.

These are not domain objects. A ScenarioRecord holds a scenario's *choices*
and its blocks; the Scenario the solver consumes also needs the curriculum,
which lives in its own collection. assemble.py joins them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from roster.domain import Block


@dataclass(frozen=True)
class SchoolRecord:
    id: str
    name: str
    cycle_days: int
    periods_per_day: int
    grades: tuple[int, ...]
    sections: tuple[str, ...]


@dataclass(frozen=True)
class UserRecord:
    id: str
    school_id: str
    email: str
    password_hash: str


@dataclass(frozen=True)
class ScenarioRecord:
    id: str
    name: str
    enabled_optional: frozenset[str] = frozenset()
    overrides: dict[tuple[int, str], int] = field(default_factory=dict)
    min_doubles: dict[tuple[int, str], int] = field(default_factory=dict)
    blocks: tuple[Block, ...] = ()
