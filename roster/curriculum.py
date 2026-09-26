"""Period counts: the CAPS requirement, optional subjects, and overrides."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CurriculumEntry:
    grade: int
    subject_code: str
    periods_per_class: int


@dataclass(frozen=True)
class Curriculum:
    entries: tuple[CurriculumEntry, ...] = ()

    def periods(self, grade: int, subject_code: str) -> int:
        for e in self.entries:
            if e.grade == grade and e.subject_code == subject_code:
                return e.periods_per_class
        return 0

    def subject_codes(self, grade: int) -> tuple[str, ...]:
        return tuple(e.subject_code for e in self.entries if e.grade == grade)


@dataclass
class Scenario:
    """One set of choices: which optional subjects run, and any CAPS overrides."""

    caps: Curriculum
    optional: Curriculum = Curriculum()
    enabled_optional: frozenset[str] = frozenset()
    overrides: dict[tuple[int, str], int] = field(default_factory=dict)
    min_doubles: dict[tuple[int, str], int] = field(default_factory=dict)
