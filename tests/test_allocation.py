from roster.allocation import (
    caps_deviation,
    demand,
    doubles_ceiling,
    effective_periods,
    filler_periods,
    max_per_day,
    required_periods,
    singles_count,
)
from roster.curriculum import Curriculum, CurriculumEntry, Scenario

CAPS_4_6 = [
    ("HL", 12), ("FAL", 10), ("MATH", 12),
    ("NST", 7), ("SS", 6), ("LS", 6), ("SPT", 2),
]
CAPS_7 = [
    ("HL", 10), ("FAL", 8), ("MATH", 9), ("NS", 6), ("SS", 6),
    ("TEC", 4), ("EMS", 4), ("LO", 4), ("CA", 4),
]
OPTIONAL = [
    (4, "BIB", 3), (5, "BIB", 4), (6, "BIB", 3), (7, "BIB", 3),
    (4, "SEP", 3),
    (7, "SPT", 2),
]


def build_scenario(enabled=("BIB", "SPT"), overrides=None) -> Scenario:
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
        enabled_optional=frozenset(enabled),
        overrides=dict(overrides or {}),
        min_doubles={},
    )


def test_caps_totals_fifty_five_in_every_grade():
    s = build_scenario(enabled=())
    for grade in (4, 5, 6, 7):
        assert sum(required_periods(s, grade).values()) == 55


def test_grade_four_to_six_share_one_allocation():
    s = build_scenario(enabled=())
    assert required_periods(s, 4) == required_periods(s, 5) == required_periods(s, 6)


def test_grade_seven_differs_from_the_lower_grades():
    s = build_scenario(enabled=())
    assert required_periods(s, 7)["HL"] == 10
    assert "NST" not in required_periods(s, 7)
    assert required_periods(s, 7)["NS"] == 6


def test_filler_per_grade_with_bible_on_sepedi_off():
    s = build_scenario(enabled=("BIB", "SPT"))
    assert filler_periods(s, 4) == 2
    assert filler_periods(s, 5) == 1  # Bible is 4 periods in grade 5
    assert filler_periods(s, 6) == 2
    assert filler_periods(s, 7) == 0


def test_all_optional_off_leaves_five_filler_periods():
    s = build_scenario(enabled=())
    for grade in (4, 5, 6, 7):
        assert filler_periods(s, grade) == 5


def test_sepedi_only_exists_in_grade_four():
    s = build_scenario(enabled=("BIB", "SEP", "SPT"))
    assert effective_periods(s, 4, "SEP") == 3
    assert effective_periods(s, 5, "SEP") == 0


# Review Focus 1: Grade 4 with both optional subjects needs 61 of 60 slots.
def test_grade_four_with_both_optional_subjects_overruns_by_one():
    s = build_scenario(enabled=("BIB", "SEP", "SPT"))
    assert sum(required_periods(s, 4).values()) == 61
    assert filler_periods(s, 4) == -1


def test_demand_omits_filler_when_it_would_be_negative():
    s = build_scenario(enabled=("BIB", "SEP", "SPT"))
    assert "STUDY" not in demand(s, 4)


def test_demand_totals_sixty_when_feasible():
    s = build_scenario(enabled=("BIB", "SPT"))
    for grade in (4, 5, 6, 7):
        assert sum(demand(s, grade).values()) == 60


def test_demand_includes_filler_as_an_ordinary_subject():
    s = build_scenario(enabled=("BIB", "SPT"))
    assert demand(s, 4)["STUDY"] == 2
    assert "STUDY" not in demand(s, 7)  # grade 7 has no slack


def test_override_changes_effective_periods_and_filler():
    s = build_scenario(enabled=("BIB", "SEP", "SPT"), overrides={(4, "SS"): 5, (4, "LS"): 5})
    assert effective_periods(s, 4, "SS") == 5
    assert sum(required_periods(s, 4).values()) == 59
    assert filler_periods(s, 4) == 1


def test_caps_deviation_reports_signed_difference():
    s = build_scenario(enabled=("BIB", "SPT"), overrides={(4, "SS"): 5})
    assert caps_deviation(s, 4)["SS"] == -1
    assert caps_deviation(s, 4)["HL"] == 0


def test_doubles_ceiling_is_n_minus_six():
    assert doubles_ceiling(12) == 6
    assert doubles_ceiling(10) == 4
    assert doubles_ceiling(9) == 3
    assert doubles_ceiling(8) == 2
    assert doubles_ceiling(6) == 0
    assert doubles_ceiling(4) == 0  # clamped, never negative


def test_singles_count_complements_the_doubles_ceiling():
    assert singles_count(12) == 0
    assert singles_count(10) == 2
    assert singles_count(8) == 4


def test_max_per_day_for_non_core_rounds_up():
    assert max_per_day(6) == 1
    assert max_per_day(7) == 2  # NST cannot fit one per day in six days
    assert max_per_day(2) == 1
    assert max_per_day(0) == 0
