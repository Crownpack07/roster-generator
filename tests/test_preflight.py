from roster.domain import DAYS, PERIODS_PER_DAY
from roster.preflight import Finding, has_errors, preflight
from tests.fixtures.meridian import ASSIGNMENT, meridian_problem


def codes(findings: list[Finding], severity: str | None = None) -> set[str]:
    return {
        f.code for f in findings if severity is None or f.severity == severity
    }


def test_the_real_school_passes_every_check():
    findings = preflight(meridian_problem())
    assert not has_errors(findings), [f.message for f in findings]


def test_errors_sort_before_warnings():
    p = meridian_problem(enabled_optional=("BIB", "SEP", "SPT"))
    findings = preflight(p)
    severities = [f.severity for f in findings]
    assert severities == sorted(severities, key=lambda s: s != "error")


# --- class_total ------------------------------------------------------------
# Review Focus 1
def test_class_total_flags_grade_four_with_both_optional_subjects():
    p = meridian_problem(enabled_optional=("BIB", "SEP", "SPT"))
    findings = preflight(p)
    assert "class_total" in codes(findings, "error")
    message = next(f.message for f in findings if f.code == "class_total")
    assert "Grade 4" in message
    assert "61" in message and "60" in message


def test_class_total_passes_when_totals_are_sixty():
    assert "class_total" not in codes(preflight(meridian_problem()), "error")


def test_class_total_accepts_an_override_that_makes_room():
    p = meridian_problem(
        enabled_optional=("BIB", "SEP", "SPT"),
        overrides={(4, "SS"): 5},
    )
    assert "class_total" not in codes(preflight(p), "error")


# --- curriculum_bounds ------------------------------------------------------
# Review Focus 3
def test_core_subject_below_six_periods_is_rejected():
    p = meridian_problem(overrides={(4, "HL"): 5})
    findings = preflight(p)
    assert "curriculum_bounds" in codes(findings, "error")
    message = next(f.message for f in findings if f.code == "curriculum_bounds")
    assert "HL" in message and "5" in message


def test_core_subject_above_twelve_periods_is_rejected():
    p = meridian_problem(overrides={(4, "HL"): 14})
    findings = preflight(p)
    assert "curriculum_bounds" in codes(findings, "error")


def test_core_subject_within_six_to_twelve_is_accepted():
    p = meridian_problem()
    assert "curriculum_bounds" not in codes(preflight(p), "error")


def test_non_core_subject_is_not_bounded_the_same_way():
    # SS at 2 periods is fine; only core subjects need one per day.
    p = meridian_problem(overrides={(4, "SS"): 2, (4, "LS"): 10})
    assert "curriculum_bounds" not in codes(preflight(p), "error")


# --- coverage ---------------------------------------------------------------
# Review Focus 5
def test_coverage_error_when_a_block_is_removed():
    trimmed = tuple(a for a in ASSIGNMENT if not (a[1] == 4 and a[2] == "LS"))
    p = meridian_problem(assignment=trimmed)
    findings = preflight(p)
    assert "coverage" in codes(findings, "error")
    assert "LS" in next(f.message for f in findings if f.code == "coverage")


def test_coverage_error_when_a_block_is_duplicated():
    doubled = ASSIGNMENT + (("Shane", 4, "LS", "ABC"),)
    p = meridian_problem(assignment=doubled)
    assert "coverage" in codes(preflight(p), "error")


# --- block_wholeness --------------------------------------------------------
def test_a_grade_subject_split_between_two_teachers_is_rejected():
    # The school's rule: one teacher owns a subject for a whole grade.
    split = tuple(
        a for a in ASSIGNMENT if not (a[1] == 7 and a[2] == "FAL")
    ) + (("Carlien", 7, "FAL", "AB"), ("Karin", 7, "FAL", "C"))
    p = meridian_problem(assignment=split)
    findings = preflight(p)
    assert "block_wholeness" in codes(findings, "error")
    message = next(f.message for f in findings if f.code == "block_wholeness")
    assert "FAL" in message and "A, B" in message


def test_block_wholeness_passes_for_the_real_school():
    assert "block_wholeness" not in codes(
        preflight(meridian_problem()), "error"
    )


# --- block_periods ----------------------------------------------------------
def test_block_periods_must_match_the_curriculum():
    from roster.curriculum import Curriculum, CurriculumEntry, Scenario
    from roster.domain import Block, Subject, Teacher
    from roster.problem import Problem

    p = Problem(
        grades=(4,),
        sections=("A",),
        subjects={"SS": Subject("SS", "Social Sciences", False, False)},
        teachers={"t1": Teacher("t1", "Tanya")},
        scenario=Scenario(caps=Curriculum((CurriculumEntry(4, "SS", 60),))),
        blocks=(Block("t1", 4, "SS", ("A",), 59),),
    )
    findings = preflight(p)
    assert "block_periods" in codes(findings, "error")
    message = next(f.message for f in findings if f.code == "block_periods")
    assert "59" in message and "60" in message


def test_block_periods_passes_for_the_real_school():
    assert "block_periods" not in codes(preflight(meridian_problem()), "error")


def test_no_coverage_error_for_the_real_school():
    assert "coverage" not in codes(preflight(meridian_problem()), "error")


# --- teacher_capacity -------------------------------------------------------
def test_teacher_over_sixty_periods_is_named():
    # Give grade 5 Afrikaans to Christa, who already holds grade 4 Afrikaans.
    # Her load becomes 36 (HL4) + 18 (NS7) + 36 (HL5) = 90 against 60.
    swapped = tuple(
        ("Christa", g, c, sec) if (g, c) == (5, "HL") else (t, g, c, sec)
        for t, g, c, sec in ASSIGNMENT
    )
    p = meridian_problem(assignment=swapped)
    findings = preflight(p)
    assert "teacher_capacity" in codes(findings, "error")
    message = next(f.message for f in findings if f.code == "teacher_capacity")
    assert "Christa" in message and "90" in message and "60" in message


def test_blocked_slots_count_against_capacity():
    # Karin holds 39 periods; block 25 slots and only 35 remain available.
    p = meridian_problem(blocked={"Karin": frozenset(range(25))})
    findings = preflight(p)
    assert "teacher_capacity" in codes(findings, "error")


def test_teacher_capacity_passes_for_the_real_school():
    assert "teacher_capacity" not in codes(preflight(meridian_problem()), "error")


# --- teacher_daily_floor ----------------------------------------------------
def test_two_twelve_period_core_blocks_need_twelve_periods_a_day():
    # Handri takes grade 4 MATH (12) and grade 6 MATH (12): 2 per class per day
    # across three classes each, so 12 periods in a 10-period day.
    swapped = tuple(
        ("Handri", g, c, sec) if (g, c) == (6, "MATH") else (t, g, c, sec)
        for t, g, c, sec in ASSIGNMENT
    )
    p = meridian_problem(assignment=swapped)
    findings = preflight(p)
    assert "teacher_daily_floor" in codes(findings, "error")
    message = next(
        f.message for f in findings if f.code == "teacher_daily_floor"
    )
    assert "Handri" in message
    assert "12" in message and str(PERIODS_PER_DAY) in message


def test_daily_floor_passes_for_the_real_school():
    assert "teacher_daily_floor" not in codes(
        preflight(meridian_problem()), "error"
    )


# --- blocked_day_conflict ---------------------------------------------------
# Review Focus 4
def test_teacher_blocked_all_day_cannot_hold_a_daily_subject():
    day_three = frozenset(range(3 * PERIODS_PER_DAY, 4 * PERIODS_PER_DAY))
    p = meridian_problem(blocked={"Christa": day_three})
    findings = preflight(p)
    assert "blocked_day_conflict" in codes(findings, "error")
    message = next(
        f.message for f in findings if f.code == "blocked_day_conflict"
    )
    assert "Christa" in message and "day 4" in message and "HL" in message


def test_teacher_blocked_part_of_a_day_is_fine():
    p = meridian_problem(blocked={"Christa": frozenset({30, 31})})
    assert "blocked_day_conflict" not in codes(preflight(p), "error")


def test_blocked_day_without_a_daily_subject_is_fine():
    # Karin holds LO, CA, BIB and STUDY, none of which must appear daily.
    day_one = frozenset(range(0, PERIODS_PER_DAY))
    p = meridian_problem(blocked={"Karin": day_one})
    assert "blocked_day_conflict" not in codes(preflight(p), "error")


# --- warnings ---------------------------------------------------------------
def test_caps_deviation_is_a_warning_not_an_error():
    p = meridian_problem(
        enabled_optional=("BIB", "SEP", "SPT"),
        overrides={(4, "SS"): 5},
    )
    findings = preflight(p)
    assert "caps_deviation" in codes(findings, "warning")
    assert "caps_deviation" not in codes(findings, "error")
    message = next(f.message for f in findings if f.code == "caps_deviation")
    assert "SS" in message and "-1" in message


def test_load_spread_warns_without_blocking():
    findings = preflight(meridian_problem())
    assert "load_spread" in codes(findings, "warning")
    assert not has_errors(findings)


def test_optional_off_warns_which_subjects_are_disabled():
    findings = preflight(meridian_problem(enabled_optional=("BIB",)))
    assert "optional_off" in codes(findings, "warning")
    message = next(f.message for f in findings if f.code == "optional_off")
    assert "SEP" in message


def test_has_errors_ignores_warnings():
    assert has_errors([Finding("x", "error", "m")]) is True
    assert has_errors([Finding("x", "warning", "m")]) is False
    assert has_errors([]) is False
