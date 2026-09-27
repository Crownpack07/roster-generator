"""JSON serialisation for problems and results."""

from __future__ import annotations

from typing import Any

from roster.curriculum import Curriculum, CurriculumEntry, Scenario
from roster.domain import Block, Subject, Teacher
from roster.problem import Problem
from roster.solve import SolveResult


def _entries_to_list(curriculum: Curriculum) -> list[dict[str, Any]]:
    return [
        {"grade": e.grade, "subject": e.subject_code, "periods": e.periods_per_class}
        for e in curriculum.entries
    ]


def _entries_from_list(rows: list[dict[str, Any]]) -> Curriculum:
    return Curriculum(
        tuple(
            CurriculumEntry(r["grade"], r["subject"], r["periods"]) for r in rows
        )
    )


def problem_to_dict(problem: Problem) -> dict[str, Any]:
    s = problem.scenario
    return {
        "grades": list(problem.grades),
        "sections": list(problem.sections),
        "subjects": [
            {
                "code": sub.code,
                "displayName": sub.display_name,
                "isCore": sub.is_core,
                "isOptional": sub.is_optional,
            }
            for sub in problem.subjects.values()
        ],
        "teachers": [
            {
                "id": t.id,
                "name": t.name,
                "blockedSlots": sorted(t.blocked_slots),
            }
            for t in problem.teachers.values()
        ],
        "scenario": {
            "caps": _entries_to_list(s.caps),
            "optional": _entries_to_list(s.optional),
            "enabledOptional": sorted(s.enabled_optional),
            "overrides": [
                {"grade": g, "subject": c, "periods": n}
                for (g, c), n in sorted(s.overrides.items())
            ],
            "minDoubles": [
                {"grade": g, "subject": c, "minimum": n}
                for (g, c), n in sorted(s.min_doubles.items())
            ],
        },
        "blocks": [
            {
                "teacherId": b.teacher_id,
                "grade": b.grade,
                "subject": b.subject_code,
                "sections": list(b.sections),
                "periodsPerClass": b.periods_per_class,
            }
            for b in problem.blocks
        ],
    }


def problem_from_dict(data: dict[str, Any]) -> Problem:
    subjects = {
        row["code"]: Subject(
            row["code"], row["displayName"], row["isCore"], row["isOptional"]
        )
        for row in data["subjects"]
    }
    teachers = {
        row["id"]: Teacher(
            row["id"], row["name"], frozenset(row.get("blockedSlots", []))
        )
        for row in data["teachers"]
    }
    raw = data["scenario"]
    scenario = Scenario(
        caps=_entries_from_list(raw["caps"]),
        optional=_entries_from_list(raw.get("optional", [])),
        enabled_optional=frozenset(raw.get("enabledOptional", [])),
        overrides={
            (r["grade"], r["subject"]): r["periods"]
            for r in raw.get("overrides", [])
        },
        min_doubles={
            (r["grade"], r["subject"]): r["minimum"]
            for r in raw.get("minDoubles", [])
        },
    )
    blocks = tuple(
        Block(
            row["teacherId"],
            row["grade"],
            row["subject"],
            tuple(row["sections"]),
            row["periodsPerClass"],
        )
        for row in data["blocks"]
    )
    return Problem(
        grades=tuple(data["grades"]),
        sections=tuple(data["sections"]),
        subjects=subjects,
        teachers=teachers,
        scenario=scenario,
        blocks=blocks,
    )


def result_to_dict(result: SolveResult) -> dict[str, Any]:
    placements = []
    if result.schedule is not None:
        placements = [
            {
                "grade": p.class_ref.grade,
                "section": p.class_ref.section,
                "subject": p.subject_code,
                "slot": p.slot,
            }
            for p in result.schedule.placements
        ]
    conflict = None
    if result.conflict is not None and result.conflict.rule_groups:
        conflict = {
            "ruleGroups": list(result.conflict.rule_groups),
            "sentences": list(result.conflict.sentences),
            "remedies": list(result.conflict.remedies),
        }
    return {
        "status": str(result.status),
        "doublesPlaced": result.doubles_placed,
        "doublesCeiling": result.doubles_ceiling,
        "wallSeconds": round(result.wall_seconds, 3),
        "findings": [
            {"code": f.code, "severity": f.severity, "message": f.message}
            for f in result.findings
        ],
        "conflict": conflict,
        "placements": placements,
    }
