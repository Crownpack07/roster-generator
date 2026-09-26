"""Meridian Primary School as a reusable Problem.

Numbers transcribed from the source spreadsheet, per spec sections 4.1-4.3.
"""

from __future__ import annotations

from roster.allocation import demand
from roster.curriculum import Curriculum, CurriculumEntry, Scenario
from roster.domain import Block, Subject, Teacher
from roster.problem import Problem

CAPS_4_6: tuple[tuple[str, int], ...] = (
    ("HL", 12), ("FAL", 10), ("MATH", 12),
    ("NST", 7), ("SS", 6), ("LS", 6), ("SPT", 2),
)
CAPS_7: tuple[tuple[str, int], ...] = (
    ("HL", 10), ("FAL", 8), ("MATH", 9), ("NS", 6), ("SS", 6),
    ("TEC", 4), ("EMS", 4), ("LO", 4), ("CA", 4),
)
OPTIONAL: tuple[tuple[int, str, int], ...] = (
    (4, "BIB", 3), (5, "BIB", 4), (6, "BIB", 3), (7, "BIB", 3),
    (4, "SEP", 3),
    (7, "SPT", 2),
)

SUBJECTS: tuple[Subject, ...] = (
    Subject("HL", "Afrikaans", is_core=True, is_optional=False),
    Subject("FAL", "English", is_core=True, is_optional=False),
    Subject("MATH", "Mathematics", is_core=True, is_optional=False),
    Subject("NST", "Natural Sciences & Technology", is_core=False, is_optional=False),
    Subject("NS", "Natural Sciences", is_core=False, is_optional=False),
    Subject("TEC", "Technology", is_core=False, is_optional=False),
    Subject("SS", "Social Sciences", is_core=False, is_optional=False),
    Subject("LS", "Life Skills", is_core=False, is_optional=False),
    Subject("LO", "Life Orientation", is_core=False, is_optional=False),
    Subject("CA", "Creative Arts", is_core=False, is_optional=False),
    Subject("EMS", "Economic & Management Sciences", is_core=False, is_optional=False),
    Subject("SPT", "Physical Education", is_core=False, is_optional=False),
    Subject("BIB", "Bible Education", is_core=False, is_optional=True),
    Subject("SEP", "Sepedi", is_core=False, is_optional=True),
    Subject("STUDY", "Study", is_core=False, is_optional=False),
)

TEACHER_NAMES: tuple[str, ...] = (
    "Nanri", "Nelmarie", "Tanya", "Carlien", "Christa", "Shane", "Karin",
    "Handri", "Marius", "Sanet", "Petra", "Corlie", "Riana", "Chrissie",
)

# (teacher name, grade, subject code, sections).
# Period counts are deliberately NOT stored here. The factory reads them from
# demand(), so toggling an optional subject or applying an override keeps every
# block consistent with the curriculum instead of drifting from it.
#
# Every block covers all three sections: one teacher owns a subject for a whole
# grade. Subjects are grouped per teacher as far as 14 staff allow, but nobody
# can hold a single subject — HL alone needs four teachers.
#
# Loads: ten teachers at 54, Chrissie and Riana 51, Karin and Shane 39.
# Total 720, maximum 54 of 60. Forced daily minimum is at most 6 of 10.
ASSIGNMENT: tuple[tuple[str, int, str, str], ...] = (
    # Grade 4
    ("Christa", 4, "HL", "ABC"),
    ("Nelmarie", 4, "FAL", "ABC"),
    ("Handri", 4, "MATH", "ABC"),
    ("Chrissie", 4, "NST", "ABC"),
    ("Marius", 4, "SS", "ABC"),
    ("Corlie", 4, "LS", "ABC"),
    ("Nelmarie", 4, "SPT", "ABC"),
    ("Karin", 4, "BIB", "ABC"),
    ("Shane", 4, "SEP", "ABC"),
    ("Karin", 4, "STUDY", "ABC"),
    # Grade 5
    ("Petra", 5, "HL", "ABC"),
    ("Nanri", 5, "FAL", "ABC"),
    ("Sanet", 5, "MATH", "ABC"),
    ("Riana", 5, "NST", "ABC"),
    ("Nelmarie", 5, "SS", "ABC"),
    ("Handri", 5, "LS", "ABC"),
    ("Nanri", 5, "SPT", "ABC"),
    ("Shane", 5, "BIB", "ABC"),
    ("Shane", 5, "STUDY", "ABC"),
    # Grade 6
    ("Corlie", 6, "HL", "ABC"),
    ("Chrissie", 6, "FAL", "ABC"),
    ("Marius", 6, "MATH", "ABC"),
    ("Tanya", 6, "NST", "ABC"),
    ("Nanri", 6, "SS", "ABC"),
    ("Sanet", 6, "LS", "ABC"),
    ("Tanya", 6, "SPT", "ABC"),
    ("Shane", 6, "BIB", "ABC"),
    ("Shane", 6, "STUDY", "ABC"),
    # Grade 7
    ("Riana", 7, "HL", "ABC"),
    ("Carlien", 7, "FAL", "ABC"),
    ("Tanya", 7, "MATH", "ABC"),
    ("Christa", 7, "NS", "ABC"),
    ("Petra", 7, "SS", "ABC"),
    ("Carlien", 7, "TEC", "ABC"),
    ("Carlien", 7, "EMS", "ABC"),
    ("Karin", 7, "LO", "ABC"),
    ("Karin", 7, "CA", "ABC"),
    ("Shane", 7, "BIB", "ABC"),
    ("Carlien", 7, "SPT", "ABC"),
)


def meridian_scenario(
    enabled_optional: tuple[str, ...] = ("BIB", "SPT"),
    overrides: dict[tuple[int, str], int] | None = None,
    min_doubles: dict[tuple[int, str], int] | None = None,
) -> Scenario:
    caps = Curriculum(
        tuple(
            CurriculumEntry(grade, code, periods)
            for grade in (4, 5, 6)
            for code, periods in CAPS_4_6
        )
        + tuple(CurriculumEntry(7, code, periods) for code, periods in CAPS_7)
    )
    optional = Curriculum(
        tuple(CurriculumEntry(g, c, p) for g, c, p in OPTIONAL)
    )
    return Scenario(
        caps=caps,
        optional=optional,
        enabled_optional=frozenset(enabled_optional),
        overrides=dict(overrides or {}),
        min_doubles=dict(min_doubles or {}),
    )


def meridian_problem(
    enabled_optional: tuple[str, ...] = ("BIB", "SPT"),
    overrides: dict[tuple[int, str], int] | None = None,
    blocked: dict[str, frozenset[int]] | None = None,
    assignment: tuple[tuple[str, int, str, str], ...] = ASSIGNMENT,
    min_doubles: dict[tuple[int, str], int] | None = None,
) -> Problem:
    blocked = blocked or {}
    scenario = meridian_scenario(enabled_optional, overrides, min_doubles)
    teachers = {
        name: Teacher(name, name, blocked.get(name, frozenset()))
        for name in TEACHER_NAMES
    }

    blocks: list[Block] = []
    for name, grade, code, sections in assignment:
        periods = demand(scenario, grade).get(code, 0)
        if periods <= 0:
            # This subject is switched off, or its filler came out at zero.
            continue
        blocks.append(Block(name, grade, code, tuple(sections), periods))

    return Problem(
        grades=(4, 5, 6, 7),
        sections=("A", "B", "C"),
        subjects={s.code: s for s in SUBJECTS},
        teachers=teachers,
        scenario=scenario,
        blocks=tuple(blocks),
    )
