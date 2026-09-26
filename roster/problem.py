"""The assembled input the solver consumes."""

from __future__ import annotations

from dataclasses import dataclass, field

from roster.allocation import demand
from roster.curriculum import Scenario
from roster.domain import FILLER_CODE, Block, ClassRef, Subject, Teacher


@dataclass
class Problem:
    grades: tuple[int, ...]
    sections: tuple[str, ...]
    subjects: dict[str, Subject]
    teachers: dict[str, Teacher]
    scenario: Scenario
    blocks: tuple[Block, ...] = field(default_factory=tuple)

    def classes(self) -> tuple[ClassRef, ...]:
        return tuple(
            ClassRef(g, s) for g in self.grades for s in self.sections
        )

    def blocks_of(self, teacher_id: str) -> tuple[Block, ...]:
        return tuple(b for b in self.blocks if b.teacher_id == teacher_id)

    def teacher_load(self, teacher_id: str) -> int:
        if teacher_id not in self.teachers:
            raise KeyError(teacher_id)
        return sum(b.total_periods for b in self.blocks_of(teacher_id))

    def block_for(self, class_ref: ClassRef, subject_code: str) -> Block | None:
        for b in self.blocks:
            if (
                b.grade == class_ref.grade
                and b.subject_code == subject_code
                and class_ref.section in b.sections
            ):
                return b
        return None

    def is_core(self, subject_code: str) -> bool:
        subject = self.subjects.get(subject_code)
        return bool(subject and subject.is_core)

    def demand_for(self, grade: int) -> dict[str, int]:
        return demand(self.scenario, grade)


def coverage_problems(
    problem: Problem,
) -> list[tuple[str, ClassRef, str, int]]:
    """Every (class, subject) triple that no block covers, or that two do.

    Filler is excluded: it is derived, so an uncovered filler slot is a
    separate finding raised by pre-flight rather than a coverage error here.
    """
    found: list[tuple[str, ClassRef, str, int]] = []
    for class_ref in problem.classes():
        for code in problem.demand_for(class_ref.grade):
            if code == FILLER_CODE:
                continue
            count = sum(
                1
                for b in problem.blocks
                if b.grade == class_ref.grade
                and b.subject_code == code
                and class_ref.section in b.sections
            )
            if count == 0:
                found.append(("unassigned", class_ref, code, 0))
            elif count > 1:
                found.append(("duplicate", class_ref, code, count))
    return found
