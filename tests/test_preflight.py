import pytest

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


# --- integrity --------------------------------------------------------------
# Runs first: the other checks would crash on, or misread, the same bad input.
def test_a_demanded_subject_with_no_subject_row_is_rejected():
    # Without the row MATH was silently non-core: it solved and verified
    # clean with grade 7 MATH missing from a day.
    p = meridian_problem()
    del p.subjects["MATH"]
    findings = preflight(p)
    assert codes(findings) == {"integrity"}
    message = findings[0].message
    assert "MATH" in message and "4, 5, 6 and 7" in message


def test_a_demanded_subject_with_no_subject_row_blocks_the_solve():
    from roster.solve import SolveStatus, solve

    p = meridian_problem()
    del p.subjects["MATH"]
    assert solve(p).status is SolveStatus.BLOCKED


def test_a_block_for_an_unknown_subject_is_rejected():
    from roster.domain import Block

    p = meridian_problem()
    p.blocks += (Block("Karin", 4, "XYZ", ("A", "B", "C"), 1),)
    findings = preflight(p)
    assert codes(findings) == {"integrity"}
    message = findings[0].message
    assert "Karin" in message and "Gr4 XYZ" in message


def test_a_block_for_an_unknown_teacher_is_rejected():
    # Used to pass pre-flight, then raise KeyError in the model.
    p = meridian_problem()
    p.teachers.pop("Karin")
    findings = preflight(p)
    assert codes(findings) == {"integrity"}
    assert all("Karin" in f.message for f in findings)
    assert any("Gr4 STUDY" in f.message for f in findings)


def test_blocked_slots_outside_the_cycle_are_rejected():
    # Used to raise ValueError from inside pre-flight.
    from roster.domain import SLOT_COUNT, Teacher

    p = meridian_problem()
    p.teachers["Karin"] = Teacher("Karin", "Karin", frozenset({-1, 3, 60}))
    findings = preflight(p)
    assert codes(findings) == {"integrity"}
    message = findings[0].message
    assert "Karin" in message and "-1, 60" in message
    assert str(SLOT_COUNT - 1) in message


def test_a_block_for_a_section_the_school_lacks_is_rejected():
    # A stale section D would make the capacity and daily-floor checks
    # count a class the model never creates.
    from roster.domain import Block

    p = meridian_problem()
    p.blocks = tuple(
        Block(b.teacher_id, b.grade, b.subject_code, ("A", "B", "C", "D"),
              b.periods_per_class)
        if (b.grade, b.subject_code) == (4, "SS") else b
        for b in p.blocks
    )
    findings = preflight(p)
    assert codes(findings) == {"integrity"}
    message = findings[0].message
    assert "Marius" in message and "Gr4 SS" in message
    assert "section D" in message


def test_a_block_for_a_grade_the_school_lacks_is_rejected():
    from roster.domain import Block

    p = meridian_problem()
    p.blocks += (Block("Karin", 9, "LO", ("A", "B", "C"), 4),)
    findings = preflight(p)
    assert codes(findings) == {"integrity"}
    message = findings[0].message
    assert "Karin" in message and "Gr9 LO" in message
    assert "grade 9" in message


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


def test_a_block_for_a_subject_the_grade_does_not_take_is_rejected():
    # NS is a real subject, but only grade 7 takes it.
    from roster.domain import Block

    p = meridian_problem()
    p.blocks += (Block("Karin", 4, "NS", ("A", "B", "C"), 6),)
    findings = preflight(p)
    assert codes(findings, "error") == {"block_periods"}
    message = next(f.message for f in findings if f.code == "block_periods")
    assert "Gr4 NS" in message and "does not take it" in message


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
# One check per (teacher, day): what the rules force onto that day against the
# periods the teacher has free on it.
def test_two_twelve_period_core_blocks_overflow_every_day():
    # Handri takes grade 4 MATH (12) and grade 6 MATH (12): 2 per class per day
    # across three classes each, plus grade 5 LS (6 periods, capped at 1 a
    # day, so 1 every day): 6 + 6 + 3 = 15 periods in a 10-period day.
    swapped = tuple(
        ("Handri", g, c, sec) if (g, c) == (6, "MATH") else (t, g, c, sec)
        for t, g, c, sec in ASSIGNMENT
    )
    p = meridian_problem(assignment=swapped)
    findings = [f for f in preflight(p) if f.code == "teacher_daily_floor"]
    assert len(findings) == 1  # one finding for all six days, not six
    message = findings[0].message
    assert findings[0].severity == "error"
    assert "Handri" in message
    assert "15" in message and str(PERIODS_PER_DAY) in message
    assert "Gr6 MATH 6" in message and "Gr5 LS 3" in message


def test_daily_floor_passes_for_the_real_school():
    assert "teacher_daily_floor" not in codes(
        preflight(meridian_problem()), "error"
    )


# Review Focus 4
def test_teacher_blocked_all_day_cannot_hold_a_daily_subject():
    day_three = frozenset(range(3 * PERIODS_PER_DAY, 4 * PERIODS_PER_DAY))
    p = meridian_problem(blocked={"Christa": day_three})
    findings = preflight(p)
    assert "teacher_daily_floor" in codes(findings, "error")
    message = next(
        f.message for f in findings if f.code == "teacher_daily_floor"
    )
    assert "Christa" in message and "day 4" in message and "HL" in message


def test_a_six_period_non_core_subject_must_appear_every_day():
    # Reviewer experiment: 6 periods under a cap of ceil(6/6) = 1 a day means
    # exactly one every day, so a teacher blocked for a whole day cannot
    # hold it, even though it is not a core subject.
    from roster.curriculum import Curriculum, CurriculumEntry, Scenario
    from roster.domain import Block, Subject, Teacher
    from roster.problem import Problem

    p = Problem(
        grades=(4,),
        sections=("A",),
        subjects={
            "SS": Subject("SS", "Social Sciences", False, False),
            "STUDY": Subject("STUDY", "Study", False, False),
        },
        teachers={
            "t1": Teacher("t1", "Marius", frozenset(range(PERIODS_PER_DAY))),
            "t2": Teacher("t2", "Karin"),
        },
        scenario=Scenario(caps=Curriculum((CurriculumEntry(4, "SS", 6),))),
        blocks=(
            Block("t1", 4, "SS", ("A",), 6),
            Block("t2", 4, "STUDY", ("A",), 54),
        ),
    )
    findings = preflight(p)
    assert codes(findings, "error") == {"teacher_daily_floor"}
    message = findings[0].message
    assert "Marius" in message and "day 1" in message and "Gr4 SS 1" in message


def test_a_partly_blocked_day_below_the_floor_is_rejected():
    # Reviewer experiment: Handri blocked for periods 1-5 of day 1. Grade 4
    # MATH forces 2 a day per class (6) and grade 5 LS 1 (3): 9 against 5.
    p = meridian_problem(blocked={"Handri": frozenset(range(5))})
    findings = [f for f in preflight(p) if f.code == "teacher_daily_floor"]
    assert len(findings) == 1
    message = findings[0].message
    assert "Handri" in message and "day 1" in message
    assert "9" in message and "5" in message


def test_a_partly_blocked_day_that_still_fits_is_fine():
    # Christa is forced into exactly 9 periods every day (grade 4 HL 6,
    # grade 7 NS 3), so one blocked period still leaves room. Two would not.
    p = meridian_problem(blocked={"Christa": frozenset({30})})
    assert "teacher_daily_floor" not in codes(preflight(p), "error")


def test_one_period_too_many_blocked_is_caught():
    p = meridian_problem(blocked={"Christa": frozenset({30, 31})})
    message = next(
        f.message for f in preflight(p) if f.code == "teacher_daily_floor"
    )
    assert "Christa" in message and "day 4" in message
    assert "9" in message and "8" in message


@pytest.mark.solver
def test_the_partly_blocked_day_that_fits_really_solves():
    from roster.solve import SolveStatus, solve

    p = meridian_problem(blocked={"Christa": frozenset({30})})
    result = solve(p, seed=1, time_limit_s=30.0)
    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)


def test_blocked_day_without_a_daily_subject_is_fine():
    # Karin holds LO, CA, BIB and STUDY, none of which must appear daily.
    day_one = frozenset(range(0, PERIODS_PER_DAY))
    p = meridian_problem(blocked={"Karin": day_one})
    assert "teacher_daily_floor" not in codes(preflight(p), "error")


# --- min_doubles --------------------------------------------------------------
def test_a_double_minimum_above_the_ceiling_is_rejected():
    # Grade 4 FAL has 10 periods: 4 days with two, so at most 4 doubles.
    p = meridian_problem(min_doubles={(4, "FAL"): 6})
    findings = preflight(p)
    assert "min_doubles" in codes(findings, "error")
    message = next(f.message for f in findings if f.code == "min_doubles")
    assert "Gr4 FAL" in message and "6" in message and "4" in message


def test_a_double_minimum_at_the_ceiling_is_accepted():
    p = meridian_problem(min_doubles={(4, "HL"): 6})
    assert "min_doubles" not in codes(preflight(p))


def test_a_double_minimum_on_a_non_core_subject_warns_it_is_ignored():
    p = meridian_problem(min_doubles={(4, "SS"): 2})
    findings = preflight(p)
    assert "min_doubles" in codes(findings, "warning")
    assert not has_errors(findings)
    message = next(f.message for f in findings if f.code == "min_doubles")
    assert "Gr4 SS" in message and "ignored" in message


def test_a_double_minimum_on_a_subject_the_grade_does_not_take_warns():
    p = meridian_problem(min_doubles={(4, "NS"): 1, (9, "HL"): 1})
    findings = [f for f in preflight(p) if f.code == "min_doubles"]
    assert {f.severity for f in findings} == {"warning"}
    assert len(findings) == 2
    assert any("Gr4 NS" in f.message for f in findings)
    assert any("Gr9 HL" in f.message for f in findings)


def test_no_nonsense_double_ceiling_for_a_core_subject_out_of_bounds():
    # 5 and 14 periods break curriculum_bounds already; the min_doubles
    # message would otherwise claim "at most -1 of the 6 days".
    for n in (5, 14):
        p = meridian_problem(
            overrides={(4, "HL"): n}, min_doubles={(4, "HL"): 3}
        )
        findings = preflight(p)
        assert "curriculum_bounds" in codes(findings, "error")
        assert "min_doubles" not in codes(findings), n


# --- overrides ----------------------------------------------------------------
def test_an_override_for_a_subject_the_grade_does_not_take_warns():
    p = meridian_problem(overrides={(4, "NS"): 5})
    findings = preflight(p)
    assert "override_ignored" in codes(findings, "warning")
    assert not has_errors(findings)
    message = next(f.message for f in findings if f.code == "override_ignored")
    assert "Gr4 NS" in message and "5" in message and "ignored" in message


def test_an_override_for_a_switched_off_optional_subject_warns():
    p = meridian_problem(overrides={(4, "SEP"): 2})  # SEP is off by default
    message = next(
        f.message for f in preflight(p) if f.code == "override_ignored"
    )
    assert "Gr4 SEP" in message and "switched off" in message


def test_an_override_the_grade_uses_is_not_flagged():
    p = meridian_problem(
        enabled_optional=("BIB", "SEP", "SPT"),
        overrides={(4, "SS"): 5, (4, "SEP"): 3},
    )
    assert "override_ignored" not in codes(preflight(p))


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
