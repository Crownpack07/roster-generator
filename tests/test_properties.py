"""Generated problems, measured to be solvable.

Each generated school gets one teacher per (grade, subject) block, so nothing
is shared and teacher capacity and daily floors can never bind. That is a real
structural difference from the Meridian fixture, which has 12 classes sharing
14 teachers and becomes unreliable under small perturbations: measured, all six
core shapes spanning this generator's range return a schedule the verifier
accepts. So a failure here points at a modelling bug rather than an
over-subscribed fixture.

"Feasible by construction" would still be too strong a claim to assert, so the
test tolerates UNKNOWN and only rules out INFEASIBLE, which for this shape
would genuinely indicate a bug.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from roster.curriculum import Curriculum, CurriculumEntry, Scenario
from roster.domain import SLOT_COUNT, Block, Subject, Teacher
from roster.problem import Problem
from roster.solve import SolveStatus, solve
from roster.verify import verify

SLOW = settings(
    # 8, not 12. CP-SAT spends its whole budget proving optimality even after
    # it has an answer, so every example costs the full time limit regardless
    # of how fast it finds a schedule — max_examples is a direct multiplier on
    # wall time. 8 examples over a three-integer generator (6-12 each) still
    # covers the range; 8 x 25s is about 200s, against 36 minutes for the
    # original 12 examples x 60s x three separate test functions.
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


@st.composite
def simple_school(draw):
    """One grade, three sections, three core and some non-core subjects."""
    hl = draw(st.integers(min_value=6, max_value=12))
    fal = draw(st.integers(min_value=6, max_value=12))
    math = draw(st.integers(min_value=6, max_value=12))
    core_total = hl + fal + math
    remaining = SLOT_COUNT - core_total
    if remaining < 0:
        remaining = 0

    non_core: list[tuple[str, int]] = []
    left = remaining
    for name in ("SS", "LS", "NST"):
        if left <= 0:
            break
        take = draw(st.integers(min_value=0, max_value=min(left, 12)))
        if take:
            non_core.append((name, take))
        left -= take
    # Split whatever is left into chunks of at most 20 periods, each with its
    # own teacher. One teacher covers all three sections of a block, so a block
    # of n periods costs that teacher 3n against a 60-period capacity — a single
    # block above 20 is rejected by pre-flight before the solver ever runs.
    #
    # An earlier draft dumped the whole remainder into one STUDY_PAD block.
    # Because each of SS/LS/NST can draw 0, that produced up to 42 periods for
    # one teacher (126 against 60). Simulated over 20,000 draws: 23.4% of
    # schools were rejected by pre-flight, worst teacher load 114. With chunking
    # the rate is 0.0% and the worst load is exactly 60. Both versions keep each
    # class's demand at exactly SLOT_COUNT; only the per-teacher load differs.
    pad = 0
    while left > 0:
        chunk = min(left, SLOT_COUNT // 3)
        non_core.append((f"STUDY_PAD_{pad}", chunk))
        left -= chunk
        pad += 1

    entries = [
        CurriculumEntry(4, "HL", hl),
        CurriculumEntry(4, "FAL", fal),
        CurriculumEntry(4, "MATH", math),
    ] + [CurriculumEntry(4, code, n) for code, n in non_core]

    subjects = {
        "HL": Subject("HL", "Home Language", True, False),
        "FAL": Subject("FAL", "First Additional Language", True, False),
        "MATH": Subject("MATH", "Mathematics", True, False),
    }
    for code, _ in non_core:
        subjects[code] = Subject(code, code.title(), False, False)

    blocks = tuple(
        Block(f"t_{e.subject_code}", 4, e.subject_code, ("A", "B", "C"),
              e.periods_per_class)
        for e in entries
    )
    teachers = {
        b.teacher_id: Teacher(b.teacher_id, b.teacher_id) for b in blocks
    }

    return Problem(
        grades=(4,),
        sections=("A", "B", "C"),
        subjects=subjects,
        teachers=teachers,
        scenario=Scenario(caps=Curriculum(tuple(entries))),
        blocks=blocks,
    )


@SLOW
@given(simple_school())
def test_a_generated_school_solves_and_every_invariant_holds(problem):
    """One solve per generated school, then every property checked on it.

    Deliberately ONE test rather than three. An earlier draft had three
    @given functions each generating and solving independently, then asserting
    one property apiece — three full solves per example for assertions that
    all read the same result. That tripled the cost for no extra coverage.

    Measured on this generator's range (core periods 6-12 each, six shapes
    spanning it): every school solves and verifies. First solution arrives in
    0.03-0.77s for five of six shapes; the outlier is the LOW-core case
    (6/6/6), which takes about 14s because a small core leaves 42 periods of
    non-core, each capped at ceil(n/6) per day — a much tighter packing. Less
    core work makes it harder, not easier.

    So the 25s budget is roughly a 1.8x margin over the worst measured case.
    UNKNOWN is tolerated anyway rather than asserted away, because a slower
    machine than the one measured could miss the 14s case, and a property test
    that fails on hardware speed teaches nothing.
    """
    result = solve(problem, seed=1, workers=1, time_limit_s=25.0)

    if result.status is SolveStatus.BLOCKED:
        # Pre-flight rejected it. That is a legitimate answer, not a bug —
        # but it must come with an error explaining why.
        assert any(f.severity == "error" for f in result.findings)
        return

    assert result.status is not SolveStatus.INFEASIBLE, (
        "a generated school has one teacher per block, so nothing is shared "
        "and capacity cannot bind; a proven contradiction here is a modelling "
        "bug",
        [f.message for f in result.findings],
    )

    if result.schedule is None:
        # UNKNOWN on a slower machine. The status assertion above still ran.
        return

    # Every property, on the one schedule we paid to compute.
    assert verify(problem, result.schedule) == []
    assert 0 <= result.doubles_placed <= result.doubles_ceiling
    for class_ref in problem.classes():
        assert len(result.schedule.for_class(class_ref)) == SLOT_COUNT
