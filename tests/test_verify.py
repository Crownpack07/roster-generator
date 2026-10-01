from roster.allocation import max_per_day
from roster.domain import (
    DAYS,
    PERIODS_PER_DAY,
    ClassRef,
    Placement,
    Schedule,
    day_of,
    slots_of_day,
)
from roster.verify import count_doubles, verify
from tests.fixtures.meridian import meridian_problem


def build_valid_schedule(problem) -> Schedule:
    """Lay out each class's demand day by day, respecting every daily cap.

    Two phases, both deterministic. Core subjects take an exact 1-or-2 per day
    split, which is the only shape the rules permit. Non-core subjects are then
    dealt to whichever days have the most room left, never exceeding their own
    daily cap. Teacher clashes are NOT avoided, by design. The layout depends
    only on the grade, so all three sections of a grade come out identical,
    and since one teacher owns a subject for the whole grade every period
    collides. Avoiding that means solving the scheduling problem — the
    solver's job. This helper exists to exercise the per-class rules; the
    clash rule has its own tests.

    A naive round-robin over days does NOT work here: day 0 attracts a period
    from every subject with a remainder and overflows, then spills into days
    that are already at their cap.
    """
    placements: list[Placement] = []
    for class_ref in problem.classes():
        wanted = problem.demand_for(class_ref.grade)
        per_day: dict[str, list[int]] = {}

        # Core: one every day, plus a second on the first (n - 6) days.
        for code, n in wanted.items():
            if problem.is_core(code):
                per_day[code] = [
                    1 + (1 if d < n - DAYS else 0) for d in range(DAYS)
                ]

        room = [
            PERIODS_PER_DAY - sum(counts[d] for counts in per_day.values())
            for d in range(DAYS)
        ]

        # Non-core, largest first: deal to the roomiest day that is under cap.
        non_core = sorted(
            ((c, n) for c, n in wanted.items() if not problem.is_core(c)),
            key=lambda pair: -pair[1],
        )
        for code, n in non_core:
            cap = max_per_day(n)
            counts = [0] * DAYS
            for _ in range(n):
                day = max(
                    (d for d in range(DAYS) if counts[d] < cap and room[d] > 0),
                    key=lambda d: room[d],
                )
                counts[day] += 1
                room[day] -= 1
            per_day[code] = counts

        for day in range(DAYS):
            slots = iter(slots_of_day(day))
            for code, counts in per_day.items():
                for _ in range(counts[day]):
                    placements.append(Placement(class_ref, code, next(slots)))

    return Schedule(tuple(placements))


def test_verifier_does_not_depend_on_the_solver():
    """The verifier must share no code with the model, even indirectly.

    Walks every roster module that roster.verify reaches through its import
    statements, parsed rather than text-scanned: the module's own docstring
    names the forbidden modules on purpose, and a comment is not a
    dependency. A forbidden import two hops away fails this as surely as a
    direct one.
    """
    import ast
    import importlib.util

    def imports_of(name: str) -> set[str]:
        # find_spec, NOT `import roster.verify as module`: roster/__init__.py
        # rebinds the package attribute `roster.verify` to the function.
        path = importlib.util.find_spec(name).origin
        tree = ast.parse(open(path, encoding="utf-8").read())
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
        return found

    reached: set[str] = set()
    todo, seen = ["roster.verify"], set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        for imported in imports_of(name):
            reached.add(imported)
            if imported.split(".")[0] == "roster":
                todo.append(imported)

    assert "roster.allocation" in reached  # the walk really goes deeper
    forbidden = {
        m
        for m in reached
        if m.split(".")[0] == "ortools" or m in ("roster.model", "roster.solve")
    }
    assert forbidden == set(), forbidden


def test_a_valid_schedule_satisfies_every_per_class_rule():
    """The helper lays out each class correctly, one class at a time.

    It cannot avoid teacher clashes, and is not meant to: it derives a class's
    layout from its GRADE alone, so 4A, 4B and 4C come out identical — and
    because one teacher owns a subject for all three sections, every period
    collides. Producing a clash-free schedule means solving the timetabling
    problem, which is the solver's job, not a test helper's.

    So this pins the seven per-class rules and nothing else. The clash rule
    gets its own pair of tests: one that it fires, one that it does not
    over-fire.
    """
    problem = meridian_problem()
    schedule = build_valid_schedule(problem)
    codes = {v.code for v in verify(problem, schedule)}
    assert codes == {"teacher_clash"}, codes


def test_teacher_clash_is_not_reported_when_the_slots_differ():
    """The clash check must not fire on a teacher's legitimate second class."""
    problem = meridian_problem()
    # Christa owns grade 4 HL across every section: two classes, two slots.
    schedule = Schedule(
        (
            Placement(ClassRef(4, "A"), "HL", 0),
            Placement(ClassRef(4, "B"), "HL", 1),
        )
    )
    codes = {v.code for v in verify(problem, schedule)}
    assert "teacher_clash" not in codes


def test_empty_schedule_reports_unfilled_slots():
    problem = meridian_problem()
    violations = verify(problem, Schedule(()))
    assert any(v.code == "slot_not_filled" for v in violations)


def test_missing_one_placement_is_caught():
    problem = meridian_problem()
    schedule = build_valid_schedule(problem)
    trimmed = Schedule(schedule.placements[1:])
    codes = {v.code for v in verify(problem, trimmed)}
    assert "slot_not_filled" in codes
    assert "period_count" in codes


def test_two_subjects_in_one_slot_is_caught():
    problem = meridian_problem()
    schedule = build_valid_schedule(problem)
    extra = Placement(ClassRef(4, "A"), "SS", schedule.placements[0].slot)
    codes = {v.code for v in verify(problem, Schedule(schedule.placements + (extra,)))}
    assert "slot_double_booked" in codes


def test_teacher_clash_is_caught():
    problem = meridian_problem()
    schedule = build_valid_schedule(problem)
    a, b = ClassRef(4, "A"), ClassRef(4, "B")
    # Christa teaches HL to 4A, 4B and 4C. Give 4B an HL period in a slot
    # where she is already with 4A.
    target = schedule.slots_of(a, "HL")[0]
    placements = tuple(
        Placement(b, "HL", p.slot)
        if (p.class_ref == b and p.slot == target)
        else p
        for p in schedule.placements
    )
    codes = {v.code for v in verify(problem, Schedule(placements))}
    assert "teacher_clash" in codes


def test_blocked_slot_violation_is_caught():
    problem = meridian_problem()
    schedule = build_valid_schedule(problem)
    used = schedule.slots_of(ClassRef(4, "A"), "HL")[0]
    blocked = meridian_problem(blocked={"Christa": frozenset({used})})
    codes = {v.code for v in verify(blocked, schedule)}
    assert "blocked_slot" in codes


def test_core_subject_missing_from_a_day_is_caught():
    problem = meridian_problem()
    schedule = build_valid_schedule(problem)
    c = ClassRef(4, "A")
    # HL runs twice on every day, so BOTH of one day's periods must go before
    # the subject is genuinely absent from that day.
    day_five = {s for s in schedule.slots_of(c, "HL") if day_of(s) == 5}
    assert day_five
    moved = tuple(
        Placement(c, "SS", p.slot)
        if (p.class_ref == c and p.slot in day_five)
        else p
        for p in schedule.placements
    )
    codes = {v.code for v in verify(problem, Schedule(moved))}
    assert "core_daily" in codes


def test_three_core_periods_in_one_day_is_caught():
    problem = meridian_problem()
    c = ClassRef(4, "A")
    schedule = build_valid_schedule(problem)
    # HL already runs twice every day, so turning any non-core period into HL
    # makes three on that day, whichever day it lands on.
    victim = next(
        p
        for p in schedule.placements
        if p.class_ref == c and not problem.is_core(p.subject_code)
    )
    swapped = tuple(
        Placement(c, "HL", p.slot) if p is victim else p
        for p in schedule.placements
    )
    codes = {v.code for v in verify(problem, Schedule(swapped))}
    assert "core_daily" in codes


def test_non_core_exceeding_its_daily_cap_is_caught():
    problem = meridian_problem()
    c = ClassRef(4, "A")
    schedule = build_valid_schedule(problem)
    # Force three SPT periods into day 0; SPT has 2 periods so its cap is 1.
    day_zero = sorted(slots_of_day(0))
    forced = []
    for p in schedule.placements:
        if p.class_ref == c and p.slot in day_zero[:3]:
            forced.append(Placement(c, "SPT", p.slot))
        else:
            forced.append(p)
    codes = {v.code for v in verify(problem, Schedule(tuple(forced)))}
    assert "spread" in codes


def test_unknown_subject_is_caught():
    problem = meridian_problem()
    schedule = build_valid_schedule(problem)
    bogus = Placement(ClassRef(4, "A"), "QUIDDITCH", 0)
    codes = {v.code for v in verify(problem, Schedule((bogus,) + schedule.placements[1:]))}
    assert "unknown_subject" in codes


# Review Focus 2: a double may not span the day boundary.
def test_count_doubles_ignores_the_day_boundary():
    problem = meridian_problem()
    c = ClassRef(4, "A")
    # HL at slots 9 and 10: consecutive integers, different days.
    schedule = Schedule((Placement(c, "HL", 9), Placement(c, "HL", 10)))
    assert count_doubles(problem, schedule) == 0


def test_count_doubles_counts_a_same_day_pair():
    problem = meridian_problem()
    c = ClassRef(4, "A")
    schedule = Schedule((Placement(c, "HL", 8), Placement(c, "HL", 9)))
    assert count_doubles(problem, schedule) == 1


def test_count_doubles_ignores_non_core_pairs():
    problem = meridian_problem()
    c = ClassRef(4, "A")
    schedule = Schedule((Placement(c, "SS", 0), Placement(c, "SS", 1)))
    assert count_doubles(problem, schedule) == 0


def test_a_block_naming_an_unknown_teacher_is_a_violation_not_a_crash():
    # verify() is public and need not follow pre-flight, so a dangling
    # teacher id is reported rather than raised as a KeyError.
    problem = meridian_problem()
    schedule = build_valid_schedule(problem)
    problem.teachers.pop("Karin")
    violations = verify(problem, schedule)
    unknown = [v for v in violations if v.code == "unknown_teacher"]
    assert unknown and all("Karin" in v.message for v in unknown)
