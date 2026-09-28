"""Build a Problem from stored documents.

This is the ONLY place a Problem is assembled. The `/problem` endpoint and
the solve job both call it, so the timetable the UI reasons about and the one
the solver receives cannot diverge. P1 §8 makes the same argument about
validation; assembly is the same trap one layer down.
"""

from __future__ import annotations

from pymongo.database import Database

from roster.curriculum import Curriculum, Scenario
from roster.problem import Problem
from roster.store.repositories import (
    CurriculumRepo,
    ScenarioRepo,
    SchoolRepo,
    SubjectRepo,
    TeacherRepo,
)


class AssemblyError(Exception):
    """A stored scenario cannot be turned into a Problem."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def assemble_problem(
    db: Database, school_id: str, scenario_id: str
) -> Problem:
    school = SchoolRepo(db).get(school_id)
    if school is None:
        raise AssemblyError(f"school {school_id} not found")

    record = ScenarioRepo(db).get(school_id, scenario_id)
    if record is None:
        raise AssemblyError(f"scenario {scenario_id} not found")

    subjects = {s.code: s for s in SubjectRepo(db).list(school_id)}
    teachers = {t.id: t for t in TeacherRepo(db).list(school_id)}

    curriculum = CurriculumRepo(db)
    caps = Curriculum(tuple(curriculum.list(school_id, "caps")))
    optional = Curriculum(tuple(curriculum.list(school_id, "optional")))

    for block in record.blocks:
        if block.teacher_id not in teachers:
            raise AssemblyError(
                f"block for grade {block.grade} {block.subject_code} names "
                f"teacher {block.teacher_id}, who does not exist"
            )
        if block.subject_code not in subjects:
            raise AssemblyError(
                f"block for grade {block.grade} names subject "
                f"{block.subject_code}, which does not exist"
            )

    scenario = Scenario(
        caps=caps,
        optional=optional,
        enabled_optional=record.enabled_optional,
        overrides=dict(record.overrides),
        min_doubles=dict(record.min_doubles),
    )
    return Problem(
        grades=school.grades,
        sections=school.sections,
        subjects=subjects,
        teachers=teachers,
        scenario=scenario,
        blocks=record.blocks,
    )
