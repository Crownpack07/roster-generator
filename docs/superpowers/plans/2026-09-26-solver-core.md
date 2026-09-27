# Solver Core Implementation Plan (Phase 1 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pure-Python library plus CLI that takes a school's curriculum, teachers and teacher↔subject assignment and produces a verified clash-free 6-day timetable — or a named, explained proof that none exists.

**Architecture:** Two independent implementations of the same rules. `roster.model` encodes the rules as a CP-SAT constraint model; `roster.verify` re-checks a finished schedule from scratch, sharing no code with the model. Every solver test asserts the verifier finds nothing. Arithmetic pre-flight checks run before the solver so the common failures get plain-English explanations instead of an UNSAT core. No web framework, no database, no HTTP — everything in this phase runs from pytest and a CLI in milliseconds.

**Tech Stack:** Python 3.12, OR-Tools CP-SAT (`ortools>=9.11`), pytest, Hypothesis. No other runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-26-timetable-generator-design.md`

**Later phases (separate plans, not this one):** Phase 2 MongoDB persistence + FastAPI; Phase 3 React UI (mockups at https://claude.ai/artifact/GLPv6vG6xeAuHaWLAGdfH2); Phase 4 PDF/Excel exports.

## Global Constraints

- Python `>=3.12`; `ortools>=9.11`; dev extras `pytest>=8.0`, `hypothesis>=6.100`. No other runtime dependencies in this phase.
- Package directory is `roster/` (spec §8). Not `rooster/`.
- **Periods are the only unit. Never model wall-clock time** — no minutes field, no duration, no conversion anywhere (spec §3.2).
- Cycle is fixed at **6 days × 10 periods = 60 slots per class**. `slot = day * 10 + period_index`, `0 <= slot < 60` (spec §3.1).
- A **double is two consecutive slots within the same day**. Slot 9 and slot 10 are NOT adjacent (spec §3.1).
- Core subjects: **`1 <= periods per day <= 2`** (spec §6.3).
- Non-core subjects: **`periods per day <= ceil(n/6)`** (spec §6.4).
- Doubles ceiling for a core subject is **`n - 6`**; `min_doubles` **defaults to 0** (spec §6.5).
- Solver objective is **maximise total doubles, and nothing else**. Teacher load fairness is explicitly NOT a solver objective — load is fixed by the assignment (spec §5.1, §6.6).
- **`INFEASIBLE` and `UNKNOWN` are never collapsed into one status.** Four statuses always distinct: `optimal`, `feasible`, `infeasible`, `unknown` (spec §7.3).
- `roster.verify` **must not import** `roster.model` or `ortools`. The whole point is independence (spec §14).
- Tests fix the CP-SAT random seed and force `num_search_workers = 1`. Production uses defaults (spec §14).
- All user-facing strings are **English only** (spec §11). Subject *display names* may name a language ("Afrikaans", "Sepedi").
- Filler is an ordinary subject with code `STUDY`, not a special case (spec §6.2).

## Review Focus

Five conditions the spec implies that no obvious task would exercise, most likely to bite first. Each has its test pinned to the task that owns the code.

1. **Grade 4 with both Bible and Sepedi needs 61 periods into 60 slots** — filler would go negative. Must be a named blocking error stating the shortfall, never a negative number, a crash, or a silently dropped period (spec §4.4). → Task 3.
2. **A "double" spanning the day boundary** — slot 9 (day 0 period 10) and slot 10 (day 1 period 1) are numerically adjacent but must never count as a double, in either the model or the verifier. → Tasks 2, 6, 9.
3. **A core subject whose period count falls outside 6–12** — a school setting HL to 5 makes "at least one every day" unsatisfiable, and setting it to 14 makes "at most two per day" unsatisfiable. Both must be reported as a clear curriculum error before the solver runs, not as a mystery infeasibility. → Task 5.
4. **A teacher blocked for an entire day while holding a subject that must appear every day** — arithmetically impossible, must be caught by pre-flight with the teacher and day named. → Task 5.
5. **Blocks that double-assign or leave unassigned a (grade, subject, class) triple**, including partial overlap where two blocks each cover some sections and together cover section B twice. Coverage must catch both directions. → Task 4.

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, dependencies, pytest config |
| `roster/__init__.py` | Public exports |
| `roster/domain.py` | Entities and slot arithmetic. Data and pure functions only, no dependencies. |
| `roster/curriculum.py` | `Curriculum`, `Scenario` — period counts, optional toggles, overrides |
| `roster/allocation.py` | Derived values: effective periods, demand, filler, doubles ceiling, CAPS deviation |
| `roster/problem.py` | `Problem` — the assembled input the solver consumes |
| `roster/verify.py` | Independent schedule verifier. **Imports neither ortools nor roster.model.** |
| `roster/preflight.py` | Layer 1 arithmetic checks producing `Finding`s |
| `roster/model.py` | CP-SAT variables, constraints, assumption literals, objective |
| `roster/diagnose.py` | Layer 2 — UNSAT core to English sentences and ranked remedies |
| `roster/solve.py` | Orchestration: pre-flight, build, solve, status mapping, result assembly |
| `roster/cli.py` | `python -m roster.cli solve <problem.json>` |
| `tests/fixtures/meridian.py` | The real school as a reusable `Problem` factory |
| `tests/test_domain.py` … `tests/test_cli.py` | One test module per source module |

---

### Task 1: Project scaffold and slot arithmetic

**Files:**
- Create: `pyproject.toml`
- Create: `roster/__init__.py`
- Create: `roster/domain.py`
- Test: `tests/test_domain.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DAYS = 6`, `PERIODS_PER_DAY = 10`, `SLOT_COUNT = 60`, `FILLER_CODE = "STUDY"`; `day_of(slot: int) -> int`, `period_of(slot: int) -> int`, `slots_of_day(day: int) -> list[int]`, `adjacent_pairs_of_day(day: int) -> list[tuple[int, int]]`, `all_adjacent_pairs() -> list[tuple[int, int]]`, `is_adjacent(a: int, b: int) -> bool`.

- [ ] **Step 1: Create the package scaffold**

`pyproject.toml`:

```toml
[project]
name = "roster"
version = "0.1.0"
description = "CAPS-compliant school timetable solver"
requires-python = ">=3.12"
dependencies = ["ortools>=9.11"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "hypothesis>=6.100"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

`roster/__init__.py`:

```python
"""CAPS-compliant school timetable solver."""
```

- [ ] **Step 2: Install it**

Run:
```bash
python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
```
Expected: installs `ortools`, `pytest`, `hypothesis` with no errors. From here on, `pytest` means `.venv/bin/pytest`.

- [ ] **Step 3: Write the failing tests for slot arithmetic**

`tests/test_domain.py`:

```python
import pytest

from roster.domain import (
    DAYS,
    PERIODS_PER_DAY,
    SLOT_COUNT,
    adjacent_pairs_of_day,
    all_adjacent_pairs,
    day_of,
    is_adjacent,
    period_of,
    slots_of_day,
)


def test_cycle_shape():
    assert DAYS == 6
    assert PERIODS_PER_DAY == 10
    assert SLOT_COUNT == 60


def test_slot_decomposes_into_day_and_period():
    assert (day_of(0), period_of(0)) == (0, 0)
    assert (day_of(9), period_of(9)) == (0, 9)
    assert (day_of(10), period_of(10)) == (1, 0)
    assert (day_of(59), period_of(59)) == (5, 9)


def test_slots_of_day_returns_ten_contiguous_slots():
    assert slots_of_day(0) == list(range(0, 10))
    assert slots_of_day(5) == list(range(50, 60))


def test_each_day_has_nine_adjacent_pairs():
    pairs = adjacent_pairs_of_day(0)
    assert len(pairs) == 9
    assert pairs[0] == (0, 1)
    assert pairs[-1] == (8, 9)


def test_all_adjacent_pairs_covers_every_day():
    assert len(all_adjacent_pairs()) == DAYS * 9


def test_day_boundary_is_not_adjacent():
    # Slot 9 is day 0 period 10; slot 10 is day 1 period 1.
    # Numerically consecutive, but a double may never span them.
    assert is_adjacent(8, 9) is True
    assert is_adjacent(9, 10) is False
    assert is_adjacent(19, 20) is False
    assert (9, 10) not in all_adjacent_pairs()


def test_adjacency_is_symmetric_and_rejects_gaps():
    assert is_adjacent(4, 3) is True
    assert is_adjacent(3, 5) is False
    assert is_adjacent(3, 3) is False


@pytest.mark.parametrize("bad", [-1, 60, 999])
def test_out_of_range_slot_rejected(bad):
    with pytest.raises(ValueError):
        day_of(bad)
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `pytest tests/test_domain.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.domain'`

- [ ] **Step 5: Implement slot arithmetic**

`roster/domain.py`:

```python
"""Entities and slot arithmetic. Pure data and pure functions."""

from __future__ import annotations

from dataclasses import dataclass

DAYS = 6
PERIODS_PER_DAY = 10
SLOT_COUNT = DAYS * PERIODS_PER_DAY

FILLER_CODE = "STUDY"


def _check_slot(slot: int) -> None:
    if not 0 <= slot < SLOT_COUNT:
        raise ValueError(f"slot {slot} outside 0..{SLOT_COUNT - 1}")


def day_of(slot: int) -> int:
    _check_slot(slot)
    return slot // PERIODS_PER_DAY


def period_of(slot: int) -> int:
    _check_slot(slot)
    return slot % PERIODS_PER_DAY


def slots_of_day(day: int) -> list[int]:
    if not 0 <= day < DAYS:
        raise ValueError(f"day {day} outside 0..{DAYS - 1}")
    start = day * PERIODS_PER_DAY
    return list(range(start, start + PERIODS_PER_DAY))


def adjacent_pairs_of_day(day: int) -> list[tuple[int, int]]:
    """The 9 consecutive slot pairs inside one day. Never spans days."""
    slots = slots_of_day(day)
    return [(slots[i], slots[i + 1]) for i in range(PERIODS_PER_DAY - 1)]


def all_adjacent_pairs() -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for day in range(DAYS):
        pairs.extend(adjacent_pairs_of_day(day))
    return pairs


def is_adjacent(a: int, b: int) -> bool:
    """True when a and b are consecutive slots within the same day."""
    _check_slot(a)
    _check_slot(b)
    return day_of(a) == day_of(b) and abs(a - b) == 1
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_domain.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml roster/__init__.py roster/domain.py tests/test_domain.py
git commit -m "feat: add package scaffold and slot arithmetic

Doubles never span the day boundary, so adjacency is defined as
same-day consecutive slots rather than consecutive integers."
```

---

### Task 2: Entities

**Files:**
- Modify: `roster/domain.py`
- Test: `tests/test_domain.py`

**Interfaces:**
- Consumes: Task 1's slot helpers.
- Produces: `ClassRef(grade: int, section: str)` with `__str__` returning e.g. `"4A"`; `Subject(code, display_name, is_core, is_optional)`; `Teacher(id, name, blocked_slots: frozenset[int])`; `Block(teacher_id, grade, subject_code, sections: tuple[str, ...], periods_per_class: int)` with `.total_periods` and `.class_refs()`; `Placement(class_ref, subject_code, slot)`; `Schedule(placements: tuple[Placement, ...])` with `.for_class(class_ref) -> dict[int, str]` and `.slots_of(class_ref, subject_code) -> list[int]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_domain.py`:

```python
from roster.domain import Block, ClassRef, Placement, Schedule, Subject, Teacher


def test_class_ref_prints_as_grade_and_section():
    assert str(ClassRef(4, "A")) == "4A"
    assert str(ClassRef(7, "C")) == "7C"


def test_block_total_is_periods_times_classes():
    block = Block("t1", 4, "HL", ("A", "B", "C"), 12)
    assert block.total_periods == 36
    assert block.class_refs() == (ClassRef(4, "A"), ClassRef(4, "B"), ClassRef(4, "C"))


def test_block_may_cover_fewer_than_all_sections():
    # Filler duty split per class, or a subject shared between two teachers.
    block = Block("t2", 5, "STUDY", ("B",), 1)
    assert block.total_periods == 1
    assert block.class_refs() == (ClassRef(5, "B"),)


def test_block_rejects_empty_sections():
    with pytest.raises(ValueError):
        Block("t1", 4, "HL", (), 12)


def test_block_rejects_duplicate_sections():
    with pytest.raises(ValueError):
        Block("t1", 4, "HL", ("A", "A"), 12)


def test_teacher_blocked_slots_are_a_frozenset():
    teacher = Teacher("t1", "Petra", frozenset({10, 11}))
    assert 10 in teacher.blocked_slots
    assert 12 not in teacher.blocked_slots


def test_schedule_maps_slots_to_subjects_per_class():
    c = ClassRef(4, "A")
    schedule = Schedule(
        (
            Placement(c, "HL", 0),
            Placement(c, "HL", 1),
            Placement(c, "MATH", 2),
        )
    )
    assert schedule.for_class(c) == {0: "HL", 1: "HL", 2: "MATH"}
    assert schedule.slots_of(c, "HL") == [0, 1]
    assert schedule.slots_of(c, "SS") == []


def test_schedule_slots_are_returned_sorted():
    c = ClassRef(6, "B")
    schedule = Schedule((Placement(c, "SS", 41), Placement(c, "SS", 7)))
    assert schedule.slots_of(c, "SS") == [7, 41]


def test_subject_flags():
    core = Subject("MATH", "Mathematics", is_core=True, is_optional=False)
    optional = Subject("BIB", "Bible Education", is_core=False, is_optional=True)
    assert core.is_core and not core.is_optional
    assert optional.is_optional and not optional.is_core
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_domain.py -v`
Expected: FAIL — `ImportError: cannot import name 'Block' from 'roster.domain'`

- [ ] **Step 3: Implement the entities**

Append to `roster/domain.py`:

```python
@dataclass(frozen=True, order=True)
class ClassRef:
    grade: int
    section: str

    def __str__(self) -> str:
        return f"{self.grade}{self.section}"


@dataclass(frozen=True)
class Subject:
    code: str
    display_name: str
    is_core: bool
    is_optional: bool


@dataclass(frozen=True)
class Teacher:
    id: str
    name: str
    blocked_slots: frozenset[int] = frozenset()


@dataclass(frozen=True)
class Block:
    teacher_id: str
    grade: int
    subject_code: str
    sections: tuple[str, ...]
    periods_per_class: int

    def __post_init__(self) -> None:
        if not self.sections:
            raise ValueError("a block must cover at least one section")
        if len(set(self.sections)) != len(self.sections):
            raise ValueError(f"duplicate sections in block {self.sections!r}")

    @property
    def total_periods(self) -> int:
        return self.periods_per_class * len(self.sections)

    def class_refs(self) -> tuple[ClassRef, ...]:
        return tuple(ClassRef(self.grade, s) for s in self.sections)


@dataclass(frozen=True)
class Placement:
    class_ref: ClassRef
    subject_code: str
    slot: int


@dataclass(frozen=True)
class Schedule:
    placements: tuple[Placement, ...] = ()

    def for_class(self, class_ref: ClassRef) -> dict[int, str]:
        return {
            p.slot: p.subject_code
            for p in self.placements
            if p.class_ref == class_ref
        }

    def slots_of(self, class_ref: ClassRef, subject_code: str) -> list[int]:
        return sorted(
            p.slot
            for p in self.placements
            if p.class_ref == class_ref and p.subject_code == subject_code
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_domain.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add roster/domain.py tests/test_domain.py
git commit -m "feat: add domain entities

Block covers an explicit tuple of sections rather than assuming all
three, so filler split per class and shared subjects use the same
concept as an ordinary full-grade block."
```

---

### Task 3: Curriculum, scenario and derived allocation

**Files:**
- Create: `roster/curriculum.py`
- Create: `roster/allocation.py`
- Test: `tests/test_allocation.py`

**Interfaces:**
- Consumes: `roster.domain` (`DAYS`, `SLOT_COUNT`, `FILLER_CODE`).
- Produces:
  - `Curriculum(entries: tuple[CurriculumEntry, ...])` with `.periods(grade, code) -> int` (0 when absent) and `.subject_codes(grade) -> tuple[str, ...]`
  - `CurriculumEntry(grade, subject_code, periods_per_class)`
  - `Scenario(caps, optional, enabled_optional: frozenset[str], overrides: dict[tuple[int, str], int], min_doubles: dict[tuple[int, str], int])`
  - `effective_periods(scenario, grade, code) -> int`
  - `required_periods(scenario, grade) -> dict[str, int]` — CAPS (post-override) plus enabled optional; excludes filler
  - `filler_periods(scenario, grade) -> int` — may be negative, deliberately
  - `demand(scenario, grade) -> dict[str, int]` — `required_periods` plus a `STUDY` entry when filler > 0
  - `doubles_ceiling(n) -> int`, `singles_count(n) -> int`, `max_per_day(n) -> int`
  - `caps_deviation(scenario, grade) -> dict[str, int]`

- [ ] **Step 1: Write the failing tests**

`tests/test_allocation.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_allocation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.allocation'`

- [ ] **Step 3: Implement the curriculum types**

`roster/curriculum.py`:

```python
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
```

- [ ] **Step 4: Implement the derived allocation**

`roster/allocation.py`:

```python
"""Values derived from curriculum plus toggles. Never stored, always computed."""

from __future__ import annotations

import math

from roster.curriculum import Scenario
from roster.domain import DAYS, FILLER_CODE, SLOT_COUNT


def effective_periods(scenario: Scenario, grade: int, subject_code: str) -> int:
    """The CAPS count, or its override, or the optional count when enabled."""
    key = (grade, subject_code)
    if key in scenario.overrides:
        return scenario.overrides[key]
    caps = scenario.caps.periods(grade, subject_code)
    if caps:
        return caps
    if subject_code in scenario.enabled_optional:
        return scenario.optional.periods(grade, subject_code)
    return 0


def required_periods(scenario: Scenario, grade: int) -> dict[str, int]:
    """Every taught subject and its period count. Excludes filler."""
    codes = list(scenario.caps.subject_codes(grade))
    for code in scenario.optional.subject_codes(grade):
        if code in scenario.enabled_optional and code not in codes:
            codes.append(code)
    result: dict[str, int] = {}
    for code in codes:
        periods = effective_periods(scenario, grade, code)
        if periods:
            result[code] = periods
    return result


def filler_periods(scenario: Scenario, grade: int) -> int:
    """Slots left over. Deliberately may be negative so callers can report it."""
    return SLOT_COUNT - sum(required_periods(scenario, grade).values())


def demand(scenario: Scenario, grade: int) -> dict[str, int]:
    """What the solver must place, filler included as an ordinary subject."""
    result = dict(required_periods(scenario, grade))
    filler = filler_periods(scenario, grade)
    if filler > 0:
        result[FILLER_CODE] = filler
    return result


def doubles_ceiling(n: int) -> int:
    """Doubles achievable for a core subject held to 1-2 periods a day."""
    return max(0, n - DAYS)


def singles_count(n: int) -> int:
    return max(0, 2 * DAYS - n)


def max_per_day(n: int) -> int:
    """Spread cap for a non-core subject: ceil(n / 6)."""
    return math.ceil(n / DAYS)


def caps_deviation(scenario: Scenario, grade: int) -> dict[str, int]:
    """Signed difference from CAPS for every CAPS subject in this grade."""
    return {
        code: effective_periods(scenario, grade, code)
        - scenario.caps.periods(grade, code)
        for code in scenario.caps.subject_codes(grade)
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_allocation.py -v`
Expected: PASS. In particular `filler_periods(s, 4) == -1` for the both-optional case — a reportable number, not a crash.

- [ ] **Step 6: Commit**

```bash
git add roster/curriculum.py roster/allocation.py tests/test_allocation.py
git commit -m "feat: add curriculum, scenario and derived allocation

Filler is allowed to compute negative so grade 4 with both Bible and
Sepedi (61 periods into 60 slots) surfaces as a reportable shortfall
rather than a crash or a silently dropped period."
```

---

### Task 4: Problem assembly and coverage

**Files:**
- Create: `roster/problem.py`
- Create: `tests/fixtures/__init__.py`
- Create: `tests/fixtures/meridian.py`
- Test: `tests/test_problem.py`

**Interfaces:**
- Consumes: `roster.domain`, `roster.curriculum`, `roster.allocation`.
- Produces:
  - `Problem(grades, sections, subjects: dict[str, Subject], teachers: dict[str, Teacher], scenario, blocks: tuple[Block, ...])`
  - `.classes() -> tuple[ClassRef, ...]`
  - `.block_for(class_ref, subject_code) -> Block | None`
  - `.blocks_of(teacher_id) -> tuple[Block, ...]`
  - `.teacher_load(teacher_id) -> int`
  - `.is_core(subject_code) -> bool`
  - `coverage_problems(problem) -> list[tuple[str, ClassRef, str, int]]` returning `(kind, class_ref, subject_code, count)` where `kind` is `"unassigned"` or `"duplicate"`
  - `tests/fixtures/meridian.py`: `meridian_problem(enabled_optional=("BIB", "SPT"), overrides=None, blocked=None) -> Problem`

- [ ] **Step 1: Write the failing tests**

`tests/test_problem.py`:

```python
import pytest

from roster.domain import Block, ClassRef, Subject, Teacher
from roster.problem import Problem, coverage_problems
from tests.fixtures.meridian import meridian_problem


def test_meridian_has_twelve_classes():
    p = meridian_problem()
    assert len(p.classes()) == 12
    assert ClassRef(4, "A") in p.classes()
    assert ClassRef(7, "C") in p.classes()


def test_meridian_has_fourteen_teachers():
    assert len(meridian_problem().teachers) == 14


def test_meridian_demand_is_seven_hundred_and_twenty_periods():
    p = meridian_problem()
    assert sum(p.teacher_load(t) for t in p.teachers) == 720


def test_meridian_covers_every_class_subject_pair():
    assert coverage_problems(meridian_problem()) == []


def test_no_meridian_teacher_is_over_capacity():
    p = meridian_problem()
    loads = {t: p.teacher_load(t) for t in p.teachers}
    assert max(loads.values()) <= 60, loads
    assert min(loads.values()) > 0, loads


def test_block_periods_match_the_curriculum_demand():
    p = meridian_problem()
    for block in p.blocks:
        assert block.periods_per_class == p.demand_for(block.grade)[
            block.subject_code
        ]


def test_every_block_covers_its_whole_grade():
    # One teacher owns a subject for all three classes of a grade.
    p = meridian_problem()
    for block in p.blocks:
        assert block.sections == ("A", "B", "C"), block


def test_one_teacher_owns_each_grade_subject_pair():
    p = meridian_problem()
    for grade in p.grades:
        for code in p.demand_for(grade):
            owners = {
                p.block_for(ClassRef(grade, s), code).teacher_id
                for s in p.sections
            }
            assert len(owners) == 1, (grade, code, owners)


def test_block_for_finds_the_owning_block():
    p = meridian_problem()
    block = p.block_for(ClassRef(4, "A"), "HL")
    assert block is not None
    assert block.grade == 4
    assert block.periods_per_class == 12


def test_block_for_returns_none_for_a_subject_that_grade_does_not_take():
    assert meridian_problem().block_for(ClassRef(4, "A"), "EMS") is None


def test_core_subjects_are_hl_fal_and_math():
    p = meridian_problem()
    assert p.is_core("HL") and p.is_core("FAL") and p.is_core("MATH")
    assert not p.is_core("SS")
    assert not p.is_core("STUDY")


def _minimal_problem(blocks) -> Problem:
    from roster.curriculum import Curriculum, CurriculumEntry, Scenario

    caps = Curriculum((CurriculumEntry(4, "SS", 60),))
    return Problem(
        grades=(4,),
        sections=("A", "B", "C"),
        subjects={"SS": Subject("SS", "Social Sciences", False, False)},
        teachers={
            "t1": Teacher("t1", "Tanya"),
            "t2": Teacher("t2", "Corlie"),
        },
        scenario=Scenario(caps=caps),
        blocks=tuple(blocks),
    )


# Review Focus 5: unassigned and double-assigned triples, including partial overlap.
def test_coverage_reports_an_unassigned_class():
    p = _minimal_problem([Block("t1", 4, "SS", ("A", "B"), 60)])
    problems = coverage_problems(p)
    assert ("unassigned", ClassRef(4, "C"), "SS", 0) in problems


def test_coverage_reports_a_duplicated_class():
    p = _minimal_problem(
        [
            Block("t1", 4, "SS", ("A", "B", "C"), 60),
            Block("t2", 4, "SS", ("A", "B", "C"), 60),
        ]
    )
    problems = coverage_problems(p)
    assert ("duplicate", ClassRef(4, "A"), "SS", 2) in problems
    assert len([x for x in problems if x[0] == "duplicate"]) == 3


def test_coverage_reports_partial_overlap_between_two_blocks():
    # t1 takes A and B, t2 takes B and C: B is covered twice, nothing is missing.
    p = _minimal_problem(
        [
            Block("t1", 4, "SS", ("A", "B"), 60),
            Block("t2", 4, "SS", ("B", "C"), 60),
        ]
    )
    problems = coverage_problems(p)
    assert problems == [("duplicate", ClassRef(4, "B"), "SS", 2)]


def test_teacher_load_sums_every_block():
    p = _minimal_problem(
        [Block("t1", 4, "SS", ("A", "B"), 30), Block("t1", 4, "SS", ("C",), 30)]
    )
    assert p.teacher_load("t1") == 90


def test_unknown_teacher_load_raises():
    with pytest.raises(KeyError):
        meridian_problem().teacher_load("nobody")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_problem.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.problem'`

- [ ] **Step 3: Implement `Problem` and coverage**

`roster/problem.py`:

```python
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
```

- [ ] **Step 4: Build the real-school fixture**

`tests/fixtures/__init__.py`:

```python
"""Test fixtures."""
```

`tests/fixtures/meridian.py`:

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_problem.py -v`
Expected: PASS.

If `test_meridian_demand_is_seven_hundred_and_twenty_periods` fails, the fixture's `ASSIGNMENT` periods do not match `demand()` — fix the fixture to match spec §4.1–4.3, never the allocation code.

- [ ] **Step 6: Commit**

```bash
git add roster/problem.py tests/fixtures tests/test_problem.py
git commit -m "feat: add problem assembly, coverage checks and school fixture

Coverage detects partial overlap between blocks, not just wholly
missing or wholly duplicated assignments."
```

---

### Task 5: Pre-flight arithmetic checks (Layer 1)

**Files:**
- Create: `roster/preflight.py`
- Test: `tests/test_preflight.py`

**Interfaces:**
- Consumes: `roster.problem`, `roster.allocation`, `roster.domain`.
- Produces:
  - `Finding(code: str, severity: str, message: str)` — `severity` is `"error"` or `"warning"`
  - `preflight(problem) -> list[Finding]` — errors first, then warnings
  - `has_errors(findings) -> bool`
  - Error codes: `curriculum_bounds`, `class_total`, `coverage`, `block_wholeness`, `block_periods`, `teacher_capacity`, `teacher_daily_floor`, `blocked_day_conflict`
  - Warning codes: `caps_deviation`, `load_spread`, `optional_off`

Each check has one test that trips it and one that does not.

- [ ] **Step 1: Write the failing tests**

`tests/test_preflight.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_preflight.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.preflight'`

- [ ] **Step 3: Implement the pre-flight checks**

`roster/preflight.py`:

```python
"""Layer 1: arithmetic checks that run before the solver.

Most real failures are counting errors, and arithmetic explains them far
better than an UNSAT core can.
"""

from __future__ import annotations

from dataclasses import dataclass

from roster.allocation import (
    caps_deviation,
    demand,
    filler_periods,
    required_periods,
)
from roster.domain import DAYS, FILLER_CODE, PERIODS_PER_DAY, SLOT_COUNT, day_of
from roster.problem import Problem, coverage_problems

CORE_MIN_PERIODS = DAYS  # at least one a day
CORE_MAX_PERIODS = 2 * DAYS  # at most two a day


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # "error" | "warning"
    message: str


def has_errors(findings: list[Finding]) -> bool:
    return any(f.severity == "error" for f in findings)


def _forced_periods_per_day(problem: Problem, grade: int, code: str) -> int:
    """The minimum this subject must occupy on any single day, per class."""
    n = demand(problem.scenario, grade).get(code, 0)
    if not n:
        return 0
    if problem.is_core(code):
        # Held to at most 2 a day across 6 days, so n periods force
        # max(1, n - 2*(DAYS-1)) on every day.
        return max(1, n - 2 * (DAYS - 1))
    return 0


def _check_curriculum_bounds(problem: Problem) -> list[Finding]:
    out: list[Finding] = []
    for grade in problem.grades:
        for code, n in demand(problem.scenario, grade).items():
            if not problem.is_core(code):
                continue
            if n < CORE_MIN_PERIODS:
                out.append(
                    Finding(
                        "curriculum_bounds",
                        "error",
                        f"Grade {grade} {code} has {n} periods but must appear "
                        f"on all {DAYS} days of the cycle. It needs at least "
                        f"{CORE_MIN_PERIODS}.",
                    )
                )
            elif n > CORE_MAX_PERIODS:
                out.append(
                    Finding(
                        "curriculum_bounds",
                        "error",
                        f"Grade {grade} {code} has {n} periods but a core "
                        f"subject may run at most 2 periods a day, so at most "
                        f"{CORE_MAX_PERIODS} across the cycle.",
                    )
                )
    return out


def _check_class_totals(problem: Problem) -> list[Finding]:
    out: list[Finding] = []
    for grade in problem.grades:
        required = sum(required_periods(problem.scenario, grade).values())
        filler = filler_periods(problem.scenario, grade)
        if filler < 0:
            out.append(
                Finding(
                    "class_total",
                    "error",
                    f"Grade {grade} needs {required} periods but only "
                    f"{SLOT_COUNT} slots exist — {abs(filler)} too many. Turn "
                    f"an optional subject off, or override a curriculum count.",
                )
            )
    return out


def _check_coverage(problem: Problem) -> list[Finding]:
    out: list[Finding] = []
    for kind, class_ref, code, count in coverage_problems(problem):
        if kind == "unassigned":
            out.append(
                Finding(
                    "coverage",
                    "error",
                    f"{class_ref} {code} has no teacher assigned.",
                )
            )
        else:
            out.append(
                Finding(
                    "coverage",
                    "error",
                    f"{class_ref} {code} is assigned to {count} blocks; "
                    f"it must be assigned exactly once.",
                )
            )
    return out


def _check_block_wholeness(problem: Problem) -> list[Finding]:
    """A block must cover every class of its grade.

    One teacher owns a subject for a whole grade, so a (grade, subject) split
    between two teachers is a configuration error rather than a supported
    arrangement.
    """
    out: list[Finding] = []
    for block in problem.blocks:
        missing = [s for s in problem.sections if s not in block.sections]
        if missing:
            teacher = problem.teachers.get(block.teacher_id)
            name = teacher.name if teacher else block.teacher_id
            out.append(
                Finding(
                    "block_wholeness",
                    "error",
                    f"{name} holds Gr{block.grade} {block.subject_code} for "
                    f"only {', '.join(block.sections)} — a subject must be "
                    f"taught to the whole grade by one teacher. Missing: "
                    f"{', '.join(missing)}.",
                )
            )
    return out


def _check_block_periods(problem: Problem) -> list[Finding]:
    """A block's stored period count must match the curriculum it serves.

    The count is stored so the editor and the database can show it, which
    means it can drift from the curriculum. This catches that.
    """
    out: list[Finding] = []
    for block in problem.blocks:
        wanted = demand(problem.scenario, block.grade).get(block.subject_code)
        if wanted is None:
            out.append(
                Finding(
                    "block_periods",
                    "error",
                    f"Gr{block.grade} {block.subject_code} is assigned but "
                    f"grade {block.grade} does not take it.",
                )
            )
        elif wanted != block.periods_per_class:
            out.append(
                Finding(
                    "block_periods",
                    "error",
                    f"Gr{block.grade} {block.subject_code} is assigned "
                    f"{block.periods_per_class} periods per class but the "
                    f"curriculum says {wanted}.",
                )
            )
    return out


def _check_teacher_capacity(problem: Problem) -> list[Finding]:
    out: list[Finding] = []
    for teacher_id, teacher in problem.teachers.items():
        load = problem.teacher_load(teacher_id)
        available = SLOT_COUNT - len(teacher.blocked_slots)
        if load > available:
            detail = ", ".join(
                f"Gr{b.grade} {b.subject_code} {b.total_periods}"
                for b in problem.blocks_of(teacher_id)
            )
            blocked_note = (
                f" ({len(teacher.blocked_slots)} slots blocked)"
                if teacher.blocked_slots
                else ""
            )
            out.append(
                Finding(
                    "teacher_capacity",
                    "error",
                    f"{teacher.name} is assigned {load} periods; only "
                    f"{available} of {SLOT_COUNT} are available"
                    f"{blocked_note}. Blocks: {detail}.",
                )
            )
    return out


def _check_teacher_daily_floor(problem: Problem) -> list[Finding]:
    out: list[Finding] = []
    for teacher_id, teacher in problem.teachers.items():
        forced = 0
        parts: list[str] = []
        for block in problem.blocks_of(teacher_id):
            per_day = _forced_periods_per_day(
                problem, block.grade, block.subject_code
            )
            if per_day:
                cost = per_day * len(block.sections)
                forced += cost
                parts.append(
                    f"Gr{block.grade} {block.subject_code} {cost}"
                )
        if forced > PERIODS_PER_DAY:
            out.append(
                Finding(
                    "teacher_daily_floor",
                    "error",
                    f"{teacher.name} is forced into {forced} periods every day "
                    f"but a day is only {PERIODS_PER_DAY} periods long. "
                    f"Daily minimums: {', '.join(parts)}.",
                )
            )
    return out


def _check_blocked_day_conflicts(problem: Problem) -> list[Finding]:
    out: list[Finding] = []
    for teacher_id, teacher in problem.teachers.items():
        if not teacher.blocked_slots:
            continue
        for day in range(DAYS):
            day_slots = {
                s for s in teacher.blocked_slots if day_of(s) == day
            }
            if len(day_slots) < PERIODS_PER_DAY:
                continue
            for block in problem.blocks_of(teacher_id):
                if problem.is_core(block.subject_code):
                    out.append(
                        Finding(
                            "blocked_day_conflict",
                            "error",
                            f"{teacher.name} is blocked for all of day "
                            f"{day + 1} but holds Gr{block.grade} "
                            f"{block.subject_code}, which must appear every "
                            f"day.",
                        )
                    )
    return out


def _warn_caps_deviation(problem: Problem) -> list[Finding]:
    out: list[Finding] = []
    for grade in problem.grades:
        deviations = {
            code: diff
            for code, diff in caps_deviation(problem.scenario, grade).items()
            if diff
        }
        if deviations:
            detail = ", ".join(
                f"{code} {diff:+d}" for code, diff in sorted(deviations.items())
            )
            out.append(
                Finding(
                    "caps_deviation",
                    "warning",
                    f"Grade {grade} deviates from CAPS: {detail}.",
                )
            )
    return out


def _warn_load_spread(problem: Problem) -> list[Finding]:
    loads = {
        t: problem.teacher_load(t) for t in problem.teachers
    }
    if not loads:
        return []
    lowest = min(loads, key=lambda t: loads[t])
    highest = max(loads, key=lambda t: loads[t])
    spread = loads[highest] - loads[lowest]
    if spread == 0:
        return []
    return [
        Finding(
            "load_spread",
            "warning",
            f"Teaching load ranges over {spread} periods — "
            f"{problem.teachers[highest].name} {loads[highest]}, "
            f"{problem.teachers[lowest].name} {loads[lowest]}. The solver "
            f"cannot change this; only the assignment can.",
        )
    ]


def _warn_optional_off(problem: Problem) -> list[Finding]:
    all_optional = {
        code
        for code, subject in problem.subjects.items()
        if subject.is_optional
    }
    off = sorted(all_optional - problem.scenario.enabled_optional)
    if not off:
        return []
    return [
        Finding(
            "optional_off",
            "warning",
            f"Optional subjects currently switched off: {', '.join(off)}.",
        )
    ]


def preflight(problem: Problem) -> list[Finding]:
    """Every arithmetic finding, errors first."""
    errors: list[Finding] = []
    errors += _check_curriculum_bounds(problem)
    errors += _check_class_totals(problem)
    errors += _check_coverage(problem)
    errors += _check_block_wholeness(problem)
    errors += _check_block_periods(problem)
    errors += _check_teacher_capacity(problem)
    errors += _check_teacher_daily_floor(problem)
    errors += _check_blocked_day_conflicts(problem)

    warnings: list[Finding] = []
    warnings += _warn_caps_deviation(problem)
    warnings += _warn_load_spread(problem)
    warnings += _warn_optional_off(problem)

    return errors + warnings
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_preflight.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add roster/preflight.py tests/test_preflight.py
git commit -m "feat: add layer 1 arithmetic pre-flight checks

Eight error checks and three warnings, each named and each explaining
the specific numbers involved. Curriculum bounds reject a core subject
outside 6-12 periods so an unsatisfiable daily rule is reported as a
curriculum error rather than a mystery infeasibility."
```

---

### Task 6: The independent verifier

**Files:**
- Create: `roster/verify.py`
- Test: `tests/test_verify.py`

**Interfaces:**
- Consumes: `roster.problem`, `roster.allocation`, `roster.domain`. **Must not import `ortools` or `roster.model`.**
- Produces:
  - `Violation(code: str, message: str)`
  - `verify(problem, schedule) -> list[Violation]`
  - `count_doubles(problem, schedule) -> int`
  - Violation codes: `slot_not_filled`, `slot_double_booked`, `period_count`, `teacher_clash`, `blocked_slot`, `core_daily`, `spread`, `unknown_subject`

Written before the solver, on purpose. It is the operative definition of a correct schedule, and it shares no code with the model so a mistake in one cannot be mirrored by a matching mistake in the other.

- [ ] **Step 1: Write the failing tests**

`tests/test_verify.py`:

```python
import pytest

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
    daily cap.

    Teacher clashes are NOT avoided, by design. The layout depends only on the
    grade, so all three sections of a grade come out identical, and since one
    teacher owns a subject for the whole grade every period collides. Avoiding
    that means solving the scheduling problem — the solver's job. This helper
    exists to exercise the per-class rules; the clash rule has its own tests.

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
    """The verifier must share no code with the model.

    Checked by parsing the real import statements rather than scanning the
    text: the module's own docstring names both forbidden modules on purpose,
    and a comment mentioning ortools is not a dependency.
    """
    import ast
    import importlib

    # importlib.import_module, NOT `import roster.verify as module`.
    # roster/__init__.py exports the verify FUNCTION at package level, which
    # rebinds the `roster.verify` attribute from the submodule to that
    # function — so the plain import form yields a function with no __file__.
    # Task 12 added those exports and broke this test, and the failure only
    # appears in a full-suite run, since no single module's tests import the
    # package root. sys.modules still holds the real module; ask for it.
    module = importlib.import_module("roster.verify")

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = {m for m in imported if m.startswith(("ortools", "roster.model"))}
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_verify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.verify'`

- [ ] **Step 3: Implement the verifier**

`roster/verify.py`:

```python
"""Independent verification of a finished schedule.

This module deliberately shares no code with the constraint model. It
re-derives every hard rule from the problem so a mistake in the model
cannot be mirrored by a matching mistake in the check.

Do not import ortools or roster.model here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from roster.allocation import demand, max_per_day
from roster.domain import (
    DAYS,
    SLOT_COUNT,
    ClassRef,
    Schedule,
    day_of,
    is_adjacent,
)
from roster.problem import Problem

CORE_MIN_PER_DAY = 1
CORE_MAX_PER_DAY = 2


@dataclass(frozen=True)
class Violation:
    code: str
    message: str


def verify(problem: Problem, schedule: Schedule) -> list[Violation]:
    """Every way this schedule breaks a hard rule. Empty means valid."""
    out: list[Violation] = []
    out += _check_unknown_subjects(problem, schedule)
    out += _check_slots_filled_once(problem, schedule)
    out += _check_period_counts(problem, schedule)
    out += _check_teacher_clashes(problem, schedule)
    out += _check_blocked_slots(problem, schedule)
    out += _check_core_daily(problem, schedule)
    out += _check_spread(problem, schedule)
    return out


def _by_class(schedule: Schedule) -> dict[ClassRef, dict[int, list[str]]]:
    table: dict[ClassRef, dict[int, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for p in schedule.placements:
        table[p.class_ref][p.slot].append(p.subject_code)
    return table


def _check_unknown_subjects(
    problem: Problem, schedule: Schedule
) -> list[Violation]:
    out: list[Violation] = []
    for p in schedule.placements:
        wanted = demand(problem.scenario, p.class_ref.grade)
        if p.subject_code not in wanted:
            out.append(
                Violation(
                    "unknown_subject",
                    f"{p.class_ref} is scheduled for {p.subject_code} in slot "
                    f"{p.slot}, which grade {p.class_ref.grade} does not take.",
                )
            )
    return out


def _check_slots_filled_once(
    problem: Problem, schedule: Schedule
) -> list[Violation]:
    out: list[Violation] = []
    table = _by_class(schedule)
    for class_ref in problem.classes():
        slots = table.get(class_ref, {})
        for slot in range(SLOT_COUNT):
            subjects = slots.get(slot, [])
            if not subjects:
                out.append(
                    Violation(
                        "slot_not_filled",
                        f"{class_ref} has nothing scheduled in slot {slot} "
                        f"(day {day_of(slot) + 1}).",
                    )
                )
            elif len(subjects) > 1:
                out.append(
                    Violation(
                        "slot_double_booked",
                        f"{class_ref} has {len(subjects)} subjects in slot "
                        f"{slot}: {', '.join(sorted(subjects))}.",
                    )
                )
    return out


def _check_period_counts(
    problem: Problem, schedule: Schedule
) -> list[Violation]:
    out: list[Violation] = []
    for class_ref in problem.classes():
        wanted = demand(problem.scenario, class_ref.grade)
        for code, expected in wanted.items():
            actual = len(schedule.slots_of(class_ref, code))
            if actual != expected:
                out.append(
                    Violation(
                        "period_count",
                        f"{class_ref} {code} has {actual} periods, expected "
                        f"{expected}.",
                    )
                )
    return out


def _check_teacher_clashes(
    problem: Problem, schedule: Schedule
) -> list[Violation]:
    occupied: dict[tuple[str, int], list[str]] = defaultdict(list)
    for p in schedule.placements:
        block = problem.block_for(p.class_ref, p.subject_code)
        if block is None:
            continue
        occupied[(block.teacher_id, p.slot)].append(
            f"{p.class_ref} {p.subject_code}"
        )
    out: list[Violation] = []
    for (teacher_id, slot), entries in sorted(occupied.items()):
        if len(entries) > 1:
            name = problem.teachers[teacher_id].name
            out.append(
                Violation(
                    "teacher_clash",
                    f"{name} is in {len(entries)} places in slot {slot}: "
                    f"{', '.join(sorted(entries))}.",
                )
            )
    return out


def _check_blocked_slots(
    problem: Problem, schedule: Schedule
) -> list[Violation]:
    out: list[Violation] = []
    for p in schedule.placements:
        block = problem.block_for(p.class_ref, p.subject_code)
        if block is None:
            continue
        teacher = problem.teachers.get(block.teacher_id)
        if teacher and p.slot in teacher.blocked_slots:
            out.append(
                Violation(
                    "blocked_slot",
                    f"{teacher.name} is scheduled in slot {p.slot} for "
                    f"{p.class_ref} {p.subject_code}, but that slot is "
                    f"blocked.",
                )
            )
    return out


def _check_core_daily(
    problem: Problem, schedule: Schedule
) -> list[Violation]:
    out: list[Violation] = []
    for class_ref in problem.classes():
        wanted = demand(problem.scenario, class_ref.grade)
        for code in wanted:
            if not problem.is_core(code):
                continue
            slots = schedule.slots_of(class_ref, code)
            per_day = [0] * DAYS
            for slot in slots:
                per_day[day_of(slot)] += 1
            for day, count in enumerate(per_day):
                if count < CORE_MIN_PER_DAY:
                    out.append(
                        Violation(
                            "core_daily",
                            f"{class_ref} {code} does not appear on day "
                            f"{day + 1}; a core subject must appear every day.",
                        )
                    )
                elif count > CORE_MAX_PER_DAY:
                    out.append(
                        Violation(
                            "core_daily",
                            f"{class_ref} {code} has {count} periods on day "
                            f"{day + 1}; at most {CORE_MAX_PER_DAY} allowed.",
                        )
                    )
    return out


def _check_spread(problem: Problem, schedule: Schedule) -> list[Violation]:
    out: list[Violation] = []
    for class_ref in problem.classes():
        wanted = demand(problem.scenario, class_ref.grade)
        for code, n in wanted.items():
            if problem.is_core(code):
                continue
            cap = max_per_day(n)
            per_day = [0] * DAYS
            for slot in schedule.slots_of(class_ref, code):
                per_day[day_of(slot)] += 1
            for day, count in enumerate(per_day):
                if count > cap:
                    out.append(
                        Violation(
                            "spread",
                            f"{class_ref} {code} has {count} periods on day "
                            f"{day + 1}; at most {cap} allowed for "
                            f"{n} periods across {DAYS} days.",
                        )
                    )
    return out


def count_doubles(problem: Problem, schedule: Schedule) -> int:
    """Same-day adjacent pairs of a core subject. Never spans days."""
    total = 0
    for class_ref in problem.classes():
        wanted = demand(problem.scenario, class_ref.grade)
        for code in wanted:
            if not problem.is_core(code):
                continue
            slots = schedule.slots_of(class_ref, code)
            for i in range(len(slots) - 1):
                if is_adjacent(slots[i], slots[i + 1]):
                    total += 1
    return total
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_verify.py -v`
Expected: PASS.

If `test_a_valid_schedule_satisfies_every_per_class_rule` reports a code other
than `teacher_clash`, the fault is in the helper or the verifier, not the
assertion — read the violation messages, which name the class, subject and day.
`teacher_clash` is expected and is what the assertion allows: the helper is
per-grade, so it cannot place three sections without collisions.

- [ ] **Step 5: Commit**

```bash
git add roster/verify.py tests/test_verify.py
git commit -m "feat: add independent schedule verifier

Written before the solver and importing neither ortools nor the model,
so a wrongly encoded constraint cannot be validated by a matching
mistake in the check. count_doubles refuses the day boundary."
```

---

### Task 7: CP-SAT model — variables and placement rules

**Files:**
- Create: `roster/model.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Consumes: `roster.problem`, `roster.allocation`, `roster.domain`.
- Produces:
  - `RULE_SLOT_FILLED`, `RULE_PERIOD_COUNTS`, `RULE_TEACHER_CLASH`, `RULE_BLOCKED_SLOTS`, `RULE_CORE_DAILY`, `RULE_SPREAD`, `RULE_MIN_DOUBLES` — string constants naming rule groups
  - `BuiltModel(model, x: dict[tuple[ClassRef, str, int], IntVar], doubles: dict[tuple[ClassRef, str, tuple[int, int]], IntVar], assumptions: dict[str, IntVar])`
  - `build(problem) -> BuiltModel`
  - `schedule_from(problem, built, solver) -> Schedule`

This task adds the four placement rules. Task 8 adds daily bounds, spread and doubles.

- [ ] **Step 1: Write the failing tests**

`tests/test_model.py`:

```python
from ortools.sat.python import cp_model

from roster.domain import SLOT_COUNT, ClassRef
from roster.model import build, schedule_from
from roster.verify import verify
from tests.fixtures.meridian import meridian_problem


def solve_built(built, time_limit=30.0):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    status = solver.Solve(built.model)
    return solver, status


def test_variable_count_is_one_per_class_subject_slot():
    problem = meridian_problem()
    built = build(problem)
    expected = sum(
        len(problem.demand_for(c.grade)) * SLOT_COUNT
        for c in problem.classes()
    )
    assert len(built.x) == expected


def test_every_rule_group_has_an_assumption_literal():
    built = build(meridian_problem())
    from roster.model import (
        RULE_BLOCKED_SLOTS,
        RULE_CORE_DAILY,
        RULE_MIN_DOUBLES,
        RULE_PERIOD_COUNTS,
        RULE_SLOT_FILLED,
        RULE_SPREAD,
        RULE_TEACHER_CLASH,
    )

    for rule in (
        RULE_SLOT_FILLED,
        RULE_PERIOD_COUNTS,
        RULE_TEACHER_CLASH,
        RULE_BLOCKED_SLOTS,
        RULE_CORE_DAILY,
        RULE_SPREAD,
        RULE_MIN_DOUBLES,
    ):
        assert rule in built.assumptions


def test_model_solves_the_real_school_and_the_verifier_agrees():
    problem = meridian_problem()
    built = build(problem)
    solver, status = solve_built(built)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    schedule = schedule_from(problem, built, solver)
    assert verify(problem, schedule) == []


def test_every_class_slot_is_filled_exactly_once():
    problem = meridian_problem()
    built = build(problem)
    solver, status = solve_built(built)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    schedule = schedule_from(problem, built, solver)
    for class_ref in problem.classes():
        assert len(schedule.for_class(class_ref)) == SLOT_COUNT


def test_blocked_slots_are_left_empty_for_that_teacher():
    blocked = frozenset({0, 1, 2})
    problem = meridian_problem(blocked={"Karin": blocked})
    built = build(problem)
    solver, status = solve_built(built)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    schedule = schedule_from(problem, built, solver)
    for p in schedule.placements:
        block = problem.block_for(p.class_ref, p.subject_code)
        if block and block.teacher_id == "Karin":
            assert p.slot not in blocked


def test_teacher_never_appears_twice_in_one_slot():
    problem = meridian_problem()
    built = build(problem)
    solver, status = solve_built(built)
    schedule = schedule_from(problem, built, solver)
    seen: set[tuple[str, int]] = set()
    for p in schedule.placements:
        block = problem.block_for(p.class_ref, p.subject_code)
        assert block is not None
        key = (block.teacher_id, p.slot)
        assert key not in seen
        seen.add(key)


def test_schedule_from_returns_only_selected_variables():
    problem = meridian_problem()
    built = build(problem)
    solver, status = solve_built(built)
    schedule = schedule_from(problem, built, solver)
    assert len(schedule.placements) == SLOT_COUNT * len(problem.classes())
    assert ClassRef(7, "C") in {p.class_ref for p in schedule.placements}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.model'`

- [ ] **Step 3: Implement variables and the placement rules**

`roster/model.py`:

```python
"""CP-SAT encoding.

One boolean per (class, subject, slot): "this class studies this subject in
this slot". Teacher occupancy is derived, because each (class, subject) pair
maps to exactly one block, which names the teacher.

Every rule group is guarded by an assumption literal so an infeasible model
can report which groups conflict.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from roster.allocation import max_per_day
from roster.domain import (
    DAYS,
    SLOT_COUNT,
    ClassRef,
    Placement,
    Schedule,
    slots_of_day,
)
from roster.problem import Problem

RULE_SLOT_FILLED = "slot_filled"
RULE_PERIOD_COUNTS = "period_counts"
RULE_TEACHER_CLASH = "teacher_clash"
RULE_BLOCKED_SLOTS = "blocked_slots"
RULE_CORE_DAILY = "core_daily"
RULE_SPREAD = "spread"
RULE_MIN_DOUBLES = "min_doubles"

ALL_RULES = (
    RULE_SLOT_FILLED,
    RULE_PERIOD_COUNTS,
    RULE_TEACHER_CLASH,
    RULE_BLOCKED_SLOTS,
    RULE_CORE_DAILY,
    RULE_SPREAD,
    RULE_MIN_DOUBLES,
)

CORE_MIN_PER_DAY = 1
CORE_MAX_PER_DAY = 2


@dataclass
class BuiltModel:
    model: cp_model.CpModel
    x: dict[tuple[ClassRef, str, int], cp_model.IntVar] = field(
        default_factory=dict
    )
    doubles: dict[
        tuple[ClassRef, str, tuple[int, int]], cp_model.IntVar
    ] = field(default_factory=dict)
    assumptions: dict[str, cp_model.IntVar] = field(default_factory=dict)


def build(problem: Problem) -> BuiltModel:
    model = cp_model.CpModel()
    built = BuiltModel(model=model)

    for rule in ALL_RULES:
        built.assumptions[rule] = model.NewBoolVar(f"assume_{rule}")
        model.AddAssumption(built.assumptions[rule])

    # Variables.
    for class_ref in problem.classes():
        for code in problem.demand_for(class_ref.grade):
            for slot in range(SLOT_COUNT):
                built.x[(class_ref, code, slot)] = model.NewBoolVar(
                    f"x_{class_ref}_{code}_{slot}"
                )

    _add_slot_filled(problem, built)
    _add_period_counts(problem, built)
    _add_teacher_rules(problem, built)
    return built


def _add_slot_filled(problem: Problem, built: BuiltModel) -> None:
    guard = built.assumptions[RULE_SLOT_FILLED]
    for class_ref in problem.classes():
        codes = list(problem.demand_for(class_ref.grade))
        for slot in range(SLOT_COUNT):
            terms = [built.x[(class_ref, c, slot)] for c in codes]
            built.model.Add(sum(terms) == 1).OnlyEnforceIf(guard)


def _add_period_counts(problem: Problem, built: BuiltModel) -> None:
    guard = built.assumptions[RULE_PERIOD_COUNTS]
    for class_ref in problem.classes():
        for code, n in problem.demand_for(class_ref.grade).items():
            terms = [
                built.x[(class_ref, code, slot)] for slot in range(SLOT_COUNT)
            ]
            built.model.Add(sum(terms) == n).OnlyEnforceIf(guard)


def _add_teacher_rules(problem: Problem, built: BuiltModel) -> None:
    clash_guard = built.assumptions[RULE_TEACHER_CLASH]
    blocked_guard = built.assumptions[RULE_BLOCKED_SLOTS]

    owned: dict[str, list[tuple[ClassRef, str]]] = defaultdict(list)
    for class_ref in problem.classes():
        for code in problem.demand_for(class_ref.grade):
            block = problem.block_for(class_ref, code)
            if block is not None:
                owned[block.teacher_id].append((class_ref, code))

    for teacher_id, pairs in owned.items():
        teacher = problem.teachers[teacher_id]
        for slot in range(SLOT_COUNT):
            terms = [built.x[(c, code, slot)] for c, code in pairs]
            if not terms:
                continue
            if slot in teacher.blocked_slots:
                built.model.Add(sum(terms) == 0).OnlyEnforceIf(blocked_guard)
            else:
                built.model.Add(sum(terms) <= 1).OnlyEnforceIf(clash_guard)


def schedule_from(
    problem: Problem, built: BuiltModel, solver: cp_model.CpSolver
) -> Schedule:
    placements: list[Placement] = []
    for (class_ref, code, slot), var in built.x.items():
        if solver.Value(var):
            placements.append(Placement(class_ref, code, slot))
    placements.sort(key=lambda p: (p.class_ref, p.slot))
    return Schedule(tuple(placements))
```

- [ ] **Step 4: Run the tests to verify the placement tests pass**

Run: `pytest tests/test_model.py -v`
Expected: `test_variable_count_is_one_per_class_subject_slot`,
`test_every_rule_group_has_an_assumption_literal`,
`test_every_class_slot_is_filled_exactly_once`,
`test_blocked_slots_are_left_empty_for_that_teacher`,
`test_teacher_never_appears_twice_in_one_slot`,
`test_schedule_from_returns_only_selected_variables` PASS.

`test_model_solves_the_real_school_and_the_verifier_agrees` FAILS with
`core_daily` and `spread` violations — those rules arrive in Task 8. This is
expected; do not weaken the verifier to make it pass.

- [ ] **Step 5: Commit**

```bash
git add roster/model.py tests/test_model.py
git commit -m "feat: add CP-SAT variables and placement rules

Exactly-one-subject-per-slot, exact period counts, teacher no-clash and
blocked slots, each guarded by an assumption literal so an infeasible
model can name the conflicting rule groups.

Daily bounds and spread follow in the next commit; the end-to-end model
test fails until then."
```

---

### Task 8: CP-SAT model — daily bounds, spread, doubles and objective

**Files:**
- Modify: `roster/model.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Consumes: Task 7's `BuiltModel`, `roster.allocation.max_per_day`, `roster.allocation.doubles_ceiling`.
- Produces: `built.doubles` populated with one variable per (class, core subject, same-day adjacent pair); objective set to maximise their sum; `total_doubles_ceiling(problem) -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_model.py`:

```python
from roster.allocation import doubles_ceiling
from roster.domain import DAYS, day_of
from roster.model import total_doubles_ceiling
from roster.verify import count_doubles


def test_double_variables_exist_only_for_same_day_pairs():
    problem = meridian_problem()
    built = build(problem)
    assert built.doubles
    for (_class_ref, _code, (a, b)) in built.doubles:
        assert day_of(a) == day_of(b)
        assert b == a + 1


# Review Focus 2
def test_no_double_variable_spans_the_day_boundary():
    built = build(meridian_problem())
    boundaries = {(d * 10 + 9, d * 10 + 10) for d in range(DAYS - 1)}
    for (_class_ref, _code, pair) in built.doubles:
        assert pair not in boundaries


def test_double_variables_exist_only_for_core_subjects():
    problem = meridian_problem()
    built = build(problem)
    for (_class_ref, code, _pair) in built.doubles:
        assert problem.is_core(code)


def test_total_doubles_ceiling_matches_the_spec_table():
    problem = meridian_problem()
    # Gr4-6: HL 12 -> 6, FAL 10 -> 4, MATH 12 -> 6 = 16 per class.
    # Gr7:   HL 10 -> 4, FAL 8 -> 2, MATH 9 -> 3 = 9 per class.
    assert doubles_ceiling(12) + doubles_ceiling(10) + doubles_ceiling(12) == 16
    assert doubles_ceiling(10) + doubles_ceiling(8) + doubles_ceiling(9) == 9
    assert total_doubles_ceiling(problem) == 16 * 9 + 9 * 3


def test_core_subjects_appear_once_or_twice_every_day():
    problem = meridian_problem()
    built = build(problem)
    solver, status = solve_built(built)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    schedule = schedule_from(problem, built, solver)
    for class_ref in problem.classes():
        for code in problem.demand_for(class_ref.grade):
            if not problem.is_core(code):
                continue
            per_day = [0] * DAYS
            for slot in schedule.slots_of(class_ref, code):
                per_day[day_of(slot)] += 1
            assert all(1 <= n <= 2 for n in per_day), (class_ref, code, per_day)


def test_non_core_respects_its_daily_cap():
    problem = meridian_problem()
    built = build(problem)
    solver, status = solve_built(built)
    schedule = schedule_from(problem, built, solver)
    assert verify(problem, schedule) == []


def test_model_and_verifier_agree_on_the_doubles_count():
    """The objective value and the independent count must match exactly.

    This cross-checks the model's reified doubles encoding against the
    verifier, which is the assertion that actually catches an encoding bug.
    The ceiling is an upper bound, not necessarily attainable, so equality
    with the ceiling is deliberately NOT asserted.
    """
    problem = meridian_problem()
    built = build(problem)
    solver, status = solve_built(built, time_limit=120.0)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    schedule = schedule_from(problem, built, solver)
    placed = count_doubles(problem, schedule)
    assert placed == int(solver.ObjectiveValue())
    assert 0 < placed <= total_doubles_ceiling(problem)


def test_min_doubles_is_honoured_when_set():
    """A minimum below the ceiling is enforced.

    Deliberately 4, not 6. Grade 4 HL has 12 periods, so its doubles ceiling
    is 6 — and demanding the ceiling as a HARD constraint is the one thing
    spec 6.5 warns against. Measured: min_doubles of 3, 4 and 5 all solve
    (first solution in about 4 seconds), while 6 returns UNKNOWN after 90
    seconds, so the ceiling is not reachable as a hard rule on this fixture.
    This test's job is to prove a minimum is honoured, not to prove the
    ceiling is attainable — which it is not.
    """
    problem = meridian_problem(min_doubles={(4, "HL"): 4})
    built = build(problem)
    solver, status = solve_built(built, time_limit=60.0)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    schedule = schedule_from(problem, built, solver)
    for section in ("A", "B", "C"):
        slots = schedule.slots_of(ClassRef(4, section), "HL")
        pairs = sum(
            1
            for i in range(len(slots) - 1)
            if slots[i + 1] == slots[i] + 1 and day_of(slots[i]) == day_of(slots[i + 1])
        )
        assert pairs >= 4
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'total_doubles_ceiling'`

- [ ] **Step 3: Implement the remaining rules and the objective**

In `roster/model.py`, **replace the existing `build` function body** with the
version below — do not add a second `def build`, which would shadow the first
and silently drop Task 7's rules. Then append the new helpers after it:

```python
def build(problem: Problem) -> BuiltModel:
    model = cp_model.CpModel()
    built = BuiltModel(model=model)

    for rule in ALL_RULES:
        built.assumptions[rule] = model.NewBoolVar(f"assume_{rule}")
        model.AddAssumption(built.assumptions[rule])

    for class_ref in problem.classes():
        for code in problem.demand_for(class_ref.grade):
            for slot in range(SLOT_COUNT):
                built.x[(class_ref, code, slot)] = model.NewBoolVar(
                    f"x_{class_ref}_{code}_{slot}"
                )

    _add_slot_filled(problem, built)
    _add_period_counts(problem, built)
    _add_teacher_rules(problem, built)
    _add_core_daily(problem, built)
    _add_spread(problem, built)
    _add_doubles(problem, built)
    _set_objective(built)
    return built


def _add_core_daily(problem: Problem, built: BuiltModel) -> None:
    guard = built.assumptions[RULE_CORE_DAILY]
    for class_ref in problem.classes():
        for code in problem.demand_for(class_ref.grade):
            if not problem.is_core(code):
                continue
            for day in range(DAYS):
                terms = [
                    built.x[(class_ref, code, slot)]
                    for slot in slots_of_day(day)
                ]
                built.model.Add(sum(terms) >= CORE_MIN_PER_DAY).OnlyEnforceIf(
                    guard
                )
                built.model.Add(sum(terms) <= CORE_MAX_PER_DAY).OnlyEnforceIf(
                    guard
                )


def _add_spread(problem: Problem, built: BuiltModel) -> None:
    guard = built.assumptions[RULE_SPREAD]
    for class_ref in problem.classes():
        for code, n in problem.demand_for(class_ref.grade).items():
            if problem.is_core(code):
                continue
            cap = max_per_day(n)
            for day in range(DAYS):
                terms = [
                    built.x[(class_ref, code, slot)]
                    for slot in slots_of_day(day)
                ]
                built.model.Add(sum(terms) <= cap).OnlyEnforceIf(guard)


def _add_doubles(problem: Problem, built: BuiltModel) -> None:
    """One reified variable per (class, core subject, same-day adjacent pair).

    Because a core subject runs at most twice a day, at most one pair per day
    can be true, so summing these variables counts doubles without the
    triple-counting a longer run would cause.
    """
    guard = built.assumptions[RULE_MIN_DOUBLES]
    for class_ref in problem.classes():
        for code in problem.demand_for(class_ref.grade):
            if not problem.is_core(code):
                continue
            pair_vars: list[cp_model.IntVar] = []
            for day in range(DAYS):
                for a, b in adjacent_pairs_of_day(day):
                    y = built.model.NewBoolVar(f"d_{class_ref}_{code}_{a}")
                    xa = built.x[(class_ref, code, a)]
                    xb = built.x[(class_ref, code, b)]
                    built.model.Add(y <= xa)
                    built.model.Add(y <= xb)
                    built.model.Add(y >= xa + xb - 1)
                    built.doubles[(class_ref, code, (a, b))] = y
                    pair_vars.append(y)
            minimum = problem.scenario.min_doubles.get(
                (class_ref.grade, code), 0
            )
            if minimum:
                built.model.Add(sum(pair_vars) >= minimum).OnlyEnforceIf(guard)


def _set_objective(built: BuiltModel) -> None:
    """Maximise total doubles. This is the only objective."""
    built.model.Maximize(sum(built.doubles.values()))


def total_doubles_ceiling(problem: Problem) -> int:
    """Doubles achievable across every class, summed."""
    total = 0
    for class_ref in problem.classes():
        for code, n in problem.demand_for(class_ref.grade).items():
            if problem.is_core(code):
                total += doubles_ceiling(n)
    return total
```

Update the imports at the top of `roster/model.py`:

```python
from roster.allocation import doubles_ceiling, max_per_day
from roster.domain import (
    DAYS,
    SLOT_COUNT,
    ClassRef,
    Placement,
    Schedule,
    adjacent_pairs_of_day,
    slots_of_day,
)
```

- [ ] **Step 4: Run the whole model suite**

Run: `pytest tests/test_model.py -v`
Expected: PASS, 15 tests — including
`test_model_solves_the_real_school_and_the_verifier_agrees`, which failed at
the end of Task 7.

If `test_model_and_verifier_agree_on_the_doubles_count` fails on the equality
between `count_doubles` and `ObjectiveValue()`, the reification in
`_add_doubles` is wrong — that is exactly the bug this test exists to catch.
Fix the model, never the verifier.

- [ ] **Step 5: Commit**

```bash
git add roster/model.py tests/test_model.py
git commit -m "feat: add daily bounds, spread, doubles and objective

Core subjects run 1-2 periods a day, which makes a double simply two
adjacent periods and removes the triple-counting a longer run would
cause. Objective maximises total doubles and nothing else; teacher load
is fixed by the assignment and deliberately absent."
```

---

### Task 9: Solve orchestration and honest status

**Files:**
- Create: `roster/solve.py`
- Test: `tests/test_solve.py`

**Interfaces:**
- Consumes: `roster.preflight`, `roster.model`, `roster.verify`.
- Produces:
  - `SolveStatus` — a `StrEnum` with `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, `UNKNOWN`, `BLOCKED`
  - `SolveResult(status, schedule, doubles_placed, doubles_ceiling, wall_seconds, findings, conflict)`
  - `solve(problem, *, time_limit_s=30.0, seed=None, workers=None, run_preflight=True) -> SolveResult`

`BLOCKED` means pre-flight found errors and the solver never ran. `INFEASIBLE` and `UNKNOWN` are never merged.

- [ ] **Step 1: Write the failing tests**

`tests/test_solve.py`:

```python
import pytest

from roster.domain import PERIODS_PER_DAY
from roster.solve import SolveResult, SolveStatus, solve
from roster.verify import verify
from tests.fixtures.meridian import meridian_problem

# 30s, not 120s. CP-SAT SPENDS its whole time budget proving optimality even
# after it has an answer: measured on this fixture, first solution arrives at
# 3.9s but a 90s limit still takes the full 90s. Since every assertion here
# accepts OPTIMAL or FEASIBLE, a generous limit buys nothing and costs minutes
# of suite time per test. 30s leaves ample margin over the measured 3.9-10.1s
# first-solution times, which assume solve() disables linearization.
SOLVE_KWARGS = {"seed": 1, "workers": 1, "time_limit_s": 30.0}


def test_the_four_statuses_are_distinct_values():
    values = {
        SolveStatus.OPTIMAL,
        SolveStatus.FEASIBLE,
        SolveStatus.INFEASIBLE,
        SolveStatus.UNKNOWN,
    }
    assert len(values) == 4
    assert SolveStatus.INFEASIBLE != SolveStatus.UNKNOWN


def test_real_school_solves_and_verifies_clean():
    problem = meridian_problem()
    result = solve(problem, **SOLVE_KWARGS)
    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE), (
        result.status,
        [f.message for f in result.findings],
    )
    assert result.schedule is not None
    assert verify(problem, result.schedule) == []


def test_doubles_ceiling_matches_the_spec_table():
    # 16 per class in grades 4-6 (nine classes), 9 per class in grade 7.
    result = solve(meridian_problem(), **SOLVE_KWARGS)
    assert result.doubles_ceiling == 16 * 9 + 9 * 3
    assert 0 < result.doubles_placed <= result.doubles_ceiling


def test_result_reports_wall_time():
    result = solve(meridian_problem(), **SOLVE_KWARGS)
    assert result.wall_seconds >= 0.0


def test_warnings_survive_a_successful_solve():
    result = solve(meridian_problem(), **SOLVE_KWARGS)
    assert any(f.severity == "warning" for f in result.findings)
    assert all(f.severity != "error" for f in result.findings)


def test_preflight_errors_block_the_solver_without_running_it():
    problem = meridian_problem(enabled_optional=("BIB", "SEP", "SPT"))
    result = solve(problem, **SOLVE_KWARGS)
    assert result.status is SolveStatus.BLOCKED
    assert result.schedule is None
    assert any(f.code == "class_total" for f in result.findings)
    assert result.wall_seconds == 0.0


def test_blocked_is_not_reported_as_infeasible():
    problem = meridian_problem(enabled_optional=("BIB", "SEP", "SPT"))
    result = solve(problem, **SOLVE_KWARGS)
    assert result.status is not SolveStatus.INFEASIBLE
    assert result.status is not SolveStatus.UNKNOWN


def test_structurally_infeasible_problem_is_proven_infeasible():
    # Force min_doubles above the achievable ceiling for one grade-4 subject.
    problem = meridian_problem(min_doubles={(4, "FAL"): 6})
    result = solve(problem, run_preflight=False, **SOLVE_KWARGS)
    assert result.status is SolveStatus.INFEASIBLE
    assert result.schedule is None


def test_a_tiny_time_limit_reports_unknown_not_infeasible():
    problem = meridian_problem()
    result = solve(problem, time_limit_s=0.001, seed=1, workers=1)
    assert result.status in (
        SolveStatus.UNKNOWN,
        SolveStatus.FEASIBLE,
        SolveStatus.OPTIMAL,
    )
    assert result.status is not SolveStatus.INFEASIBLE


def test_repeated_solves_agree_on_properties_not_on_the_exact_schedule():
    """Two runs with the same seed may differ, and that is expected.

    Spec 14 originally claimed fixing the seed and forcing one worker makes
    runs reproducible. Measured: it does not. A wall-clock budget stops the
    search wherever it happens to be when the clock expires, so identical
    seeds legitimately return different schedules. Reproducibility would need
    the search to run to completion, which on this model it does not. So
    assert properties, never an exact schedule.
    """
    problem = meridian_problem()
    a = solve(problem, **SOLVE_KWARGS)
    b = solve(problem, **SOLVE_KWARGS)
    assert a.status == b.status
    assert a.doubles_ceiling == b.doubles_ceiling
    for result in (a, b):
        if result.schedule is not None:
            assert verify(problem, result.schedule) == []


def test_blocked_slots_are_respected_when_a_timetable_is_found():
    """Any timetable the solver returns honours blocked slots.

    Asserted conditionally, on purpose. Blocking slots can make the whole
    problem unsolvable inside the time limit: measured, blocking two of
    Petra's slots returns UNKNOWN at 200s, and blocking Karin's fails where
    blocking Shane's succeeds, despite identical loads and both holding only
    non-core subjects. Requiring a solve here would be asserting solver luck.
    The unconditional guarantee lives in
    tests/test_model.py::test_blocked_slots_are_left_empty_for_that_teacher.
    """
    blocked = frozenset({PERIODS_PER_DAY, PERIODS_PER_DAY + 1})
    problem = meridian_problem(blocked={"Shane": blocked})
    result = solve(problem, **SOLVE_KWARGS)
    assert result.status is not SolveStatus.BLOCKED
    assert result.status is not SolveStatus.INFEASIBLE
    if result.schedule is None:
        return
    assert verify(problem, result.schedule) == []
    for placement in result.schedule.placements:
        block = problem.block_for(placement.class_ref, placement.subject_code)
        if block is not None and block.teacher_id == "Shane":
            assert placement.slot not in blocked


def test_sepedi_on_with_an_override_is_accepted():
    """The CAPS-override path reaches the solver and reports its deviation.

    Grade 4 fits 61 periods into 60 only by shaving two CAPS subjects. What
    this pins is that the override path yields a well-formed problem that
    clears pre-flight and is reported as deviating — not that a timetable is
    found, which measurement shows may not happen inside the limit.
    """
    problem = meridian_problem(
        enabled_optional=("BIB", "SEP", "SPT"),
        overrides={(4, "SS"): 5, (4, "LS"): 5},
    )
    result = solve(problem, **SOLVE_KWARGS)
    assert result.status is not SolveStatus.BLOCKED, [
        f.message for f in result.findings if f.severity == "error"
    ]
    assert result.status is not SolveStatus.INFEASIBLE
    assert any(f.code == "caps_deviation" for f in result.findings)
    if result.schedule is not None:
        assert verify(problem, result.schedule) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_solve.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.solve'`

- [ ] **Step 3: Implement solve orchestration**

`roster/solve.py`:

```python
"""Orchestration: pre-flight, build, solve, map status, assemble the result."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

from ortools.sat.python import cp_model

from roster.diagnose import ConflictReport, explain
from roster.model import build, schedule_from, total_doubles_ceiling
from roster.preflight import Finding, has_errors, preflight
from roster.problem import Problem
from roster.domain import Schedule
from roster.verify import count_doubles


class SolveStatus(StrEnum):
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


@dataclass
class SolveResult:
    status: SolveStatus
    schedule: Schedule | None = None
    doubles_placed: int = 0
    doubles_ceiling: int = 0
    wall_seconds: float = 0.0
    findings: list[Finding] = field(default_factory=list)
    conflict: ConflictReport | None = None


_STATUS_MAP = {
    cp_model.OPTIMAL: SolveStatus.OPTIMAL,
    cp_model.FEASIBLE: SolveStatus.FEASIBLE,
    cp_model.INFEASIBLE: SolveStatus.INFEASIBLE,
    cp_model.MODEL_INVALID: SolveStatus.UNKNOWN,
    cp_model.UNKNOWN: SolveStatus.UNKNOWN,
}


def solve(
    problem: Problem,
    *,
    time_limit_s: float = 30.0,
    seed: int | None = None,
    workers: int | None = None,
    run_preflight: bool = True,
) -> SolveResult:
    findings = preflight(problem) if run_preflight else []
    ceiling = total_doubles_ceiling(problem)

    if run_preflight and has_errors(findings):
        return SolveResult(
            status=SolveStatus.BLOCKED,
            doubles_ceiling=ceiling,
            findings=findings,
        )

    built = build(problem)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    if seed is not None:
        solver.parameters.random_seed = seed
    if workers is not None:
        solver.parameters.num_search_workers = workers

    started = time.monotonic()
    raw = solver.Solve(built.model)
    elapsed = time.monotonic() - started
    status = _STATUS_MAP.get(raw, SolveStatus.UNKNOWN)

    if status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE):
        schedule = schedule_from(problem, built, solver)
        return SolveResult(
            status=status,
            schedule=schedule,
            doubles_placed=count_doubles(problem, schedule),
            doubles_ceiling=ceiling,
            wall_seconds=elapsed,
            findings=findings,
        )

    conflict = None
    if status is SolveStatus.INFEASIBLE:
        conflict = explain(problem, built, solver)

    return SolveResult(
        status=status,
        doubles_ceiling=ceiling,
        wall_seconds=elapsed,
        findings=findings,
        conflict=conflict,
    )
```

- [ ] **Step 4: Create a stub for `roster.diagnose` so imports resolve**

Task 10 replaces this. Create `roster/diagnose.py`:

```python
"""Layer 2: translate an UNSAT core into English. Filled out in Task 10."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConflictReport:
    rule_groups: tuple[str, ...] = ()
    sentences: tuple[str, ...] = ()
    remedies: tuple[str, ...] = ()


def explain(problem, built, solver) -> ConflictReport:
    return ConflictReport()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_solve.py -v`
Expected: PASS.

If `test_real_school_solves_and_verifies_clean` reports BLOCKED, read the
error findings — the fixture's assignment has drifted from the curriculum and
the fixture is what needs fixing, not the checks.

- [ ] **Step 6: Run the whole suite**

Run: `pytest -v`
Expected: PASS, all modules.

- [ ] **Step 7: Commit**

```bash
git add roster/solve.py roster/diagnose.py tests/test_solve.py
git commit -m "feat: add solve orchestration with honest status reporting

Five distinct statuses. BLOCKED means pre-flight errors stopped the
solver from running; INFEASIBLE means proven impossible; UNKNOWN means
no proof either way. None of the three is ever collapsed into another."
```

---

### Task 10: Conflict explanation (Layer 2)

**Files:**
- Modify: `roster/diagnose.py`
- Test: `tests/test_diagnose.py`

**Interfaces:**
- Consumes: `roster.model` rule constants, `roster.problem`, CP-SAT's
  `solver.SufficientAssumptionsForInfeasibility()`.
- Produces:
  - `ConflictReport(rule_groups, sentences, remedies)` — all tuples of `str`
  - `explain(problem, built, solver) -> ConflictReport`
  - `RULE_SENTENCES: dict[str, str]` — one English sentence per rule group
  - `remedies_for(problem, rule_groups) -> tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

`tests/test_diagnose.py`:

```python
from ortools.sat.python import cp_model

from roster.diagnose import RULE_SENTENCES, ConflictReport, explain, remedies_for
from roster.model import ALL_RULES, RULE_CORE_DAILY, RULE_MIN_DOUBLES, build
from roster.solve import SolveStatus, solve
from tests.fixtures.meridian import meridian_problem


def test_every_rule_group_has_an_english_sentence():
    for rule in ALL_RULES:
        assert rule in RULE_SENTENCES
        assert RULE_SENTENCES[rule].endswith(".")


def test_explain_names_the_conflicting_rule_groups():
    problem = meridian_problem(min_doubles={(4, "FAL"): 6})
    built = build(problem)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    status = solver.Solve(built.model)
    assert status == cp_model.INFEASIBLE

    report = explain(problem, built, solver)
    assert isinstance(report, ConflictReport)
    assert report.rule_groups
    assert set(report.rule_groups) <= set(ALL_RULES)


def test_explain_produces_one_sentence_per_rule_group():
    problem = meridian_problem(min_doubles={(4, "FAL"): 6})
    built = build(problem)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    solver.Solve(built.model)
    report = explain(problem, built, solver)
    assert len(report.sentences) == len(report.rule_groups)
    for sentence in report.sentences:
        assert sentence == sentence.strip()
        assert sentence


def test_explain_offers_at_least_one_remedy():
    problem = meridian_problem(min_doubles={(4, "FAL"): 6})
    result = solve(
        problem, run_preflight=False, seed=1, workers=1, time_limit_s=30.0
    )
    assert result.status is SolveStatus.INFEASIBLE
    assert result.conflict is not None
    assert result.conflict.remedies


def test_min_doubles_conflict_suggests_relaxing_min_doubles():
    remedies = remedies_for(
        meridian_problem(min_doubles={(4, "FAL"): 6}),
        (RULE_MIN_DOUBLES, RULE_CORE_DAILY),
    )
    joined = " ".join(remedies)
    assert "minimum" in joined.lower()


def test_teacher_clash_conflict_suggests_reassignment_with_capacity():
    from roster.model import RULE_TEACHER_CLASH

    remedies = remedies_for(meridian_problem(), (RULE_TEACHER_CLASH,))
    joined = " ".join(remedies)
    assert "reassign" in joined.lower()
    # Names at least one teacher who has spare capacity.
    assert any(name in joined for name in ("Shane", "Corlie", "Tanya"))


def test_explain_returns_empty_report_for_a_feasible_model():
    problem = meridian_problem()
    built = build(problem)
    solver = cp_model.CpSolver()
    # 30s, not 120s: CP-SAT spends its whole budget proving optimality even
    # after it has an answer, and this solve only needs to reach a feasible
    # model so explain() has something non-infeasible to look at. Measured
    # first solution on this fixture is ~10.5s with linearization disabled.
    solver.parameters.max_time_in_seconds = 30.0
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    solver.parameters.linearization_level = 0
    solver.Solve(built.model)
    report = explain(problem, built, solver)
    assert report.rule_groups == ()
    assert report.sentences == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_diagnose.py -v`
Expected: FAIL — `ImportError: cannot import name 'RULE_SENTENCES'`

- [ ] **Step 3: Implement the explanation**

Replace `roster/diagnose.py` entirely:

```python
"""Layer 2: turn an UNSAT core into English sentences and ranked remedies.

Each rule group in the model carries an assumption literal. When the model is
infeasible, CP-SAT returns the smallest set of those literals that cannot all
hold. This module maps them back to sentences a person can act on.
"""

from __future__ import annotations

from dataclasses import dataclass

from roster.domain import DAYS, PERIODS_PER_DAY, SLOT_COUNT
from roster.model import (
    RULE_BLOCKED_SLOTS,
    RULE_CORE_DAILY,
    RULE_MIN_DOUBLES,
    RULE_PERIOD_COUNTS,
    RULE_SLOT_FILLED,
    RULE_SPREAD,
    RULE_TEACHER_CLASH,
)
from roster.problem import Problem

RULE_SENTENCES: dict[str, str] = {
    RULE_SLOT_FILLED: (
        f"Every class must have exactly one subject in each of its "
        f"{SLOT_COUNT} slots."
    ),
    RULE_PERIOD_COUNTS: (
        "Every subject must hit its exact period count for the cycle."
    ),
    RULE_TEACHER_CLASH: (
        "No teacher can be with two classes in the same period."
    ),
    RULE_BLOCKED_SLOTS: (
        "Teachers cannot be scheduled in slots marked unavailable."
    ),
    RULE_CORE_DAILY: (
        f"Home Language, First Additional Language and Mathematics must each "
        f"appear on all {DAYS} days, at most twice a day."
    ),
    RULE_SPREAD: (
        "Non-core subjects must spread across the cycle rather than clump "
        "into one day."
    ),
    RULE_MIN_DOUBLES: (
        "Subjects with a minimum double-period count must reach it."
    ),
}


@dataclass(frozen=True)
class ConflictReport:
    rule_groups: tuple[str, ...] = ()
    sentences: tuple[str, ...] = ()
    remedies: tuple[str, ...] = ()


def _spare_capacity(problem: Problem) -> list[tuple[str, int]]:
    """Teachers with room, most spare first."""
    spare = []
    for teacher_id, teacher in problem.teachers.items():
        available = SLOT_COUNT - len(teacher.blocked_slots)
        room = available - problem.teacher_load(teacher_id)
        if room > 0:
            spare.append((teacher.name, room))
    spare.sort(key=lambda pair: -pair[1])
    return spare


def remedies_for(
    problem: Problem, rule_groups: tuple[str, ...]
) -> tuple[str, ...]:
    """Ranked smallest changes that could restore feasibility."""
    out: list[str] = []

    if RULE_MIN_DOUBLES in rule_groups:
        wanted = ", ".join(
            f"Gr{grade} {code} (minimum {n})"
            for (grade, code), n in sorted(problem.scenario.min_doubles.items())
        )
        out.append(
            f"Lower or remove the double-period minimum. Currently set: "
            f"{wanted or 'none'}. The default is 0, which lets the objective "
            f"earn doubles instead of demanding them."
        )

    if RULE_TEACHER_CLASH in rule_groups or RULE_BLOCKED_SLOTS in rule_groups:
        spare = _spare_capacity(problem)
        if spare:
            listed = ", ".join(
                f"{name} (+{room} free)" for name, room in spare[:3]
            )
            out.append(
                f"Reassign one of the conflicting blocks to a teacher with "
                f"room: {listed}."
            )
        else:
            out.append(
                "Reassign one of the conflicting blocks. No teacher currently "
                "has spare capacity, so a block has to move off someone else "
                "first."
            )

    if RULE_BLOCKED_SLOTS in rule_groups:
        blocked = [
            (t.name, len(t.blocked_slots))
            for t in problem.teachers.values()
            if t.blocked_slots
        ]
        if blocked:
            listed = ", ".join(
                f"{name} ({count} slots)" for name, count in sorted(blocked)
            )
            out.append(f"Free up blocked slots: {listed}.")

    if RULE_CORE_DAILY in rule_groups:
        out.append(
            f"Allow a core subject to miss a day, or to run more than twice "
            f"in one day. Both are currently hard rules and a day is only "
            f"{PERIODS_PER_DAY} periods long."
        )

    if RULE_SPREAD in rule_groups:
        out.append(
            "Raise the daily cap on a non-core subject so it may run more "
            "than once in a day."
        )

    if RULE_PERIOD_COUNTS in rule_groups or RULE_SLOT_FILLED in rule_groups:
        out.append(
            "Change a period count: turn an optional subject off, or override "
            "a curriculum count so the grade's total fits "
            f"{SLOT_COUNT} slots."
        )

    return tuple(out)


def explain(problem: Problem, built, solver) -> ConflictReport:
    """Read the UNSAT core off the solver and translate it.

    Returns an empty report when the model was not infeasible.
    """
    try:
        indices = solver.SufficientAssumptionsForInfeasibility()
    except Exception:  # solver holds no core for a feasible solve
        return ConflictReport()

    if not indices:
        return ConflictReport()

    by_index = {
        var.Index(): rule for rule, var in built.assumptions.items()
    }
    groups = tuple(
        dict.fromkeys(
            by_index[i] for i in indices if i in by_index
        )
    )
    if not groups:
        return ConflictReport()

    sentences = tuple(RULE_SENTENCES[g] for g in groups)
    return ConflictReport(
        rule_groups=groups,
        sentences=sentences,
        remedies=remedies_for(problem, groups),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_diagnose.py -v`
Expected: PASS.

If `test_explain_names_the_conflicting_rule_groups` gets an empty tuple, check
that `build()` calls `model.AddAssumption` for every rule — without it CP-SAT
returns no core.

- [ ] **Step 5: Commit**

```bash
git add roster/diagnose.py tests/test_diagnose.py
git commit -m "feat: add layer 2 conflict explanation

Maps the UNSAT core's assumption literals back to English sentences and
ranked remedies, naming the teachers who actually have spare capacity."
```

---

### Task 11: Property-based tests

**Files:**
- Create: `tests/test_properties.py`

**Interfaces:**
- Consumes: everything. Adds no production code.
- Produces: generated schools measured to be solvable (one teacher per block, so
  nothing is shared and capacity cannot bind), and a single property test that
  pays for one solve per example and then checks every invariant on it —
  verifier-clean, doubles within the ceiling, every class slot filled. Rules out
  INFEASIBLE, tolerates UNKNOWN.

- [ ] **Step 1: Write the property tests**

`tests/test_properties.py`:

```python
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
    spanning it, with the leftover periods chunked so no teacher exceeds
    capacity): every school solves and verifies. First solution arrives in
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
```

- [ ] **Step 2: Run the property tests**

Run: `pytest tests/test_properties.py -v`
Expected: PASS, in roughly 200s. That is one solve per example, 8 examples, each
capped at 25s. Do not be alarmed by a run that takes minutes — CP-SAT spends its
whole budget proving optimality after it already has an answer, so each example
costs its full limit.

If a generated case fails, Hypothesis prints the minimal reproducing problem.
Copy it into `tests/test_solve.py` as a named regression test before fixing the
bug.

- [ ] **Step 3: Commit**

```bash
git add tests/test_properties.py
git commit -m "test: add property-based tests over generated schools

Generated problems give one teacher per block so nothing is shared and
capacity cannot bind, which means a failure points at a modelling bug
rather than an over-subscribed fixture. Measured: all six core shapes
spanning the generator's range return a verifier-clean schedule.

One test asserting every invariant on a single solve, not three tests
each paying for their own. Eight examples at a 25s cap is about 200s;
three functions at twelve examples and 60s would have been 36 minutes,
because CP-SAT spends its whole budget proving optimality after it
already has an answer."
```

---

### Task 12: CLI and JSON round-trip

**Files:**
- Create: `roster/io.py`
- Create: `roster/cli.py`
- Create: `tests/test_cli.py`
- Modify: `roster/__init__.py`

**Interfaces:**
- Consumes: `roster.solve`, `roster.problem`, `roster.curriculum`, `roster.domain`.
- Produces:
  - `problem_from_dict(data: dict) -> Problem`
  - `problem_to_dict(problem: Problem) -> dict`
  - `result_to_dict(result: SolveResult) -> dict`
  - `main(argv: list[str] | None = None) -> int` — `roster.cli solve <file.json>`;
    exit code 0 for `optimal`/`feasible`, 1 for `blocked`/`infeasible`/`unknown`

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
import json

from roster.cli import main
from roster.io import problem_from_dict, problem_to_dict, result_to_dict
from roster.solve import SolveStatus, solve
from roster.verify import verify
from tests.fixtures.meridian import meridian_problem


def test_problem_survives_a_json_round_trip():
    original = meridian_problem()
    data = json.loads(json.dumps(problem_to_dict(original)))
    restored = problem_from_dict(data)
    assert restored.classes() == original.classes()
    assert set(restored.teachers) == set(original.teachers)
    assert restored.demand_for(4) == original.demand_for(4)
    assert len(restored.blocks) == len(original.blocks)


def test_round_tripped_problem_still_solves_and_verifies():
    original = meridian_problem()
    restored = problem_from_dict(
        json.loads(json.dumps(problem_to_dict(original)))
    )
    result = solve(restored, seed=1, workers=1, time_limit_s=30.0)
    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)
    assert verify(restored, result.schedule) == []


def test_blocked_slots_survive_the_round_trip():
    original = meridian_problem(blocked={"Petra": frozenset({10, 11})})
    restored = problem_from_dict(
        json.loads(json.dumps(problem_to_dict(original)))
    )
    assert restored.teachers["Petra"].blocked_slots == frozenset({10, 11})


def test_result_to_dict_is_json_serialisable():
    result = solve(meridian_problem(), seed=1, workers=1, time_limit_s=30.0)
    text = json.dumps(result_to_dict(result))
    payload = json.loads(text)
    assert payload["status"] in ("optimal", "feasible")
    assert 0 < payload["doublesPlaced"] <= payload["doublesCeiling"]
    assert len(payload["placements"]) == 720


def test_result_to_dict_carries_findings_and_conflict_keys():
    result = solve(
        meridian_problem(enabled_optional=("BIB", "SEP", "SPT")),
        seed=1,
        workers=1,
    )
    payload = result_to_dict(result)
    assert payload["status"] == "blocked"
    assert payload["placements"] == []
    assert any(f["code"] == "class_total" for f in payload["findings"])
    assert payload["conflict"] is None


def test_cli_solves_a_file_and_exits_zero(tmp_path, capsys):
    path = tmp_path / "problem.json"
    path.write_text(json.dumps(problem_to_dict(meridian_problem())))
    code = main(["solve", str(path), "--seed", "1", "--workers", "1",
                 "--time-limit", "30"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] in ("optimal", "feasible")


def test_cli_exits_one_when_preflight_blocks(tmp_path, capsys):
    problem = meridian_problem(enabled_optional=("BIB", "SEP", "SPT"))
    path = tmp_path / "problem.json"
    path.write_text(json.dumps(problem_to_dict(problem)))
    code = main(["solve", str(path)])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"


def test_cli_rejects_a_missing_file(tmp_path, capsys):
    code = main(["solve", str(tmp_path / "nope.json")])
    assert code == 2
    assert "not found" in capsys.readouterr().err


def test_cli_rejects_a_structurally_invalid_problem_file(tmp_path, capsys):
    """Valid JSON, wrong shape: exit 2 with a message, never a traceback.

    Distinct from both a missing file and unparseable JSON. A hand-edited or
    truncated problem file lands here, and `problem_from_dict` indexes keys
    directly, so without a guard this surfaces as an uncaught KeyError.
    """
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"grades": [4], "sections": ["A"]}))
    code = main(["solve", str(path)])
    assert code == 2
    err = capsys.readouterr().err
    assert "not a valid problem file" in err
    assert "Traceback" not in err


def test_overrides_and_min_doubles_survive_the_round_trip():
    """The highest-risk fields in the whole serialisation layer.

    Both are dicts keyed by a `(grade, subject_code)` TUPLE, and JSON cannot
    express a tuple key at all — they serialise as lists of objects and must be
    reassembled on the way back. Every other test here leaves both dicts empty,
    so without this one the transform is only ever exercised on the empty case.
    Phase 2's API serves this shape, and a key that fails to reassemble would
    silently discard a school's deliberate curriculum overrides.
    """
    original = meridian_problem(
        overrides={(4, "SS"): 5, (7, "HL"): 9},
        min_doubles={(4, "HL"): 4, (5, "MATH"): 3},
    )
    restored = problem_from_dict(
        json.loads(json.dumps(problem_to_dict(original)))
    )
    assert restored.scenario.overrides == {(4, "SS"): 5, (7, "HL"): 9}
    assert restored.scenario.min_doubles == {(4, "HL"): 4, (5, "MATH"): 3}
    # Empty dicts must come back empty, not as something falsy-but-different.
    plain = problem_from_dict(
        json.loads(json.dumps(problem_to_dict(meridian_problem())))
    )
    assert plain.scenario.overrides == {}
    assert plain.scenario.min_doubles == {}


def test_result_to_dict_serialises_a_populated_conflict():
    """The conflict branch, which every other test leaves as None.

    A minimum above the achievable ceiling is proven INFEASIBLE — grade 4 FAL
    has 10 periods, so its doubles ceiling is 4 and a minimum of 6 cannot hold.
    That is what populates the report.
    """
    problem = meridian_problem(min_doubles={(4, "FAL"): 6})
    result = solve(
        problem, run_preflight=False, seed=1, workers=1, time_limit_s=30.0
    )
    assert result.status is SolveStatus.INFEASIBLE
    payload = json.loads(json.dumps(result_to_dict(result)))
    assert payload["status"] == "infeasible"
    assert payload["placements"] == []
    assert payload["conflict"] is not None
    assert payload["conflict"]["ruleGroups"]
    assert payload["conflict"]["sentences"]
    assert payload["conflict"]["remedies"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.cli'`

- [ ] **Step 3: Implement JSON serialisation**

`roster/io.py`:

```python
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
```

- [ ] **Step 4: Implement the CLI**

`roster/cli.py`:

```python
"""Command line entry point: python -m roster.cli solve problem.json"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from roster.io import problem_from_dict, result_to_dict
from roster.solve import SolveStatus, solve

_SUCCESS = (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="roster")
    sub = parser.add_subparsers(dest="command", required=True)

    solve_cmd = sub.add_parser("solve", help="solve a problem file")
    solve_cmd.add_argument("path", help="path to a problem JSON file")
    solve_cmd.add_argument("--time-limit", type=float, default=30.0)
    solve_cmd.add_argument("--seed", type=int, default=None)
    solve_cmd.add_argument("--workers", type=int, default=None)

    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.is_file():
        print(f"error: {path} not found", file=sys.stderr)
        return 2

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: {path} is not valid JSON ({exc})", file=sys.stderr)
        return 2

    try:
        problem = problem_from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        # Valid JSON, wrong shape: a missing or misspelled key, a truncated
        # write, an older schema. problem_from_dict indexes directly, so this
        # would otherwise surface as an uncaught KeyError — a traceback and
        # exit 1, where the contract says exit 2 with a message.
        print(
            f"error: {path} is not a valid problem file ({exc!r})",
            file=sys.stderr,
        )
        return 2

    result = solve(
        problem,
        time_limit_s=args.time_limit,
        seed=args.seed,
        workers=args.workers,
    )
    print(json.dumps(result_to_dict(result), indent=2))
    return 0 if result.status in _SUCCESS else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Export the public surface**

Replace `roster/__init__.py`:

```python
"""CAPS-compliant school timetable solver."""

from roster.domain import (
    DAYS,
    PERIODS_PER_DAY,
    SLOT_COUNT,
    Block,
    ClassRef,
    Placement,
    Schedule,
    Subject,
    Teacher,
)
from roster.preflight import Finding, preflight
from roster.problem import Problem
from roster.solve import SolveResult, SolveStatus, solve
from roster.verify import Violation, count_doubles, verify

__all__ = [
    "DAYS",
    "PERIODS_PER_DAY",
    "SLOT_COUNT",
    "Block",
    "ClassRef",
    "Finding",
    "Placement",
    "Problem",
    "Schedule",
    "SolveResult",
    "SolveStatus",
    "Subject",
    "Teacher",
    "Violation",
    "count_doubles",
    "preflight",
    "solve",
    "verify",
]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 7: Run the whole suite and exercise the CLI by hand**

Run:
```bash
pytest -v
python - <<'PY'
import json
from roster.io import problem_to_dict
from tests.fixtures.meridian import meridian_problem
open("/tmp/meridian.json", "w").write(json.dumps(problem_to_dict(meridian_problem())))
PY
python -m roster.cli solve /tmp/meridian.json --seed 1 --workers 1 --time-limit 30 | head -20
```
Expected: full suite PASS; the CLI prints `"status": "optimal"` (or
`"feasible"` if the time limit bites first) and a `"doublesCeiling"` of 171.

- [ ] **Step 8: Commit**

```bash
git add roster/io.py roster/cli.py roster/__init__.py tests/test_cli.py
git commit -m "feat: add JSON serialisation and CLI

Problems round-trip through JSON without loss, which is the boundary
phase 2's API will serve. Exit code distinguishes a solved timetable
from blocked, infeasible or unknown."
```

---

## Self-Review Notes

Recorded so the executor knows what was checked.

**Spec coverage:**

| Spec section | Task |
|---|---|
| §3.1 cycle, slots, doubles | 1 |
| §3.2 periods not hours | Global Constraints; no duration field exists anywhere |
| §3.3 entities, §3.4 subjects | 2, 4 |
| §3.5 derived values | 3 |
| §4.1–4.3 curriculum data | 3, 4 (fixture) |
| §4.4 grade 4 impossibility | 3 (arithmetic), 5 (`class_total` error) |
| §5.1 assignment owns load | 5 (`load_spread` warning), 8 (no load term in objective) |
| §5.2 scheduling owns timing | 7, 8 |
| §6.1 variables | 7 |
| §6.2 hard constraints | 7, 8 |
| §6.3 core 1–2 per day | 8 |
| §6.4 non-core spread | 8 |
| §6.5 doubles, `minDoubles` default 0 | 3, 8 |
| §6.6 single objective | 8 |
| §6.7 emergent structure, not a rule | 8 — no constraint confines core to the morning |
| §7.1 layer 1 | 5 |
| §7.2 layer 2 | 10 |
| §7.3 four statuses | 9 |
| §7.4 warnings | 5 |
| §8 module boundaries | File Structure; Task 6 asserts the verifier's independence |
| §13 CAPS override | 3, 5 |
| §14 testing | 6, 11, and every task's TDD cycle |

**Not in this plan, by design:** §9 persistence, §10 auth, §11 UI, §12 exports.
Those are phases 2–4 with their own plans.

**Review Focus coverage:**

1. Negative filler → `test_grade_four_with_both_optional_subjects_overruns_by_one` (Task 3), `test_class_total_flags_grade_four_with_both_optional_subjects` (Task 5)
2. Day-boundary double → `test_day_boundary_is_not_adjacent` (Task 1), `test_count_doubles_ignores_the_day_boundary` (Task 6), `test_no_double_variable_spans_the_day_boundary` (Task 8)
3. Core count outside 6–12 → `test_core_subject_below_six_periods_is_rejected`, `test_core_subject_above_twelve_periods_is_rejected` (Task 5)
4. Whole-day block plus daily subject → `test_teacher_blocked_all_day_cannot_hold_a_daily_subject` (Task 5)
5. Coverage overlap → `test_coverage_reports_partial_overlap_between_two_blocks` (Task 4)

**Fixture loads, hand-checked:** Carlien, Christa, Corlie, Handri, Marius,
Nanri, Nelmarie, Petra, Sanet and Tanya 54; Chrissie and Riana 51; Karin and
Shane 39. Total 720, maximum 54 of 60, spread 15. Every block covers all three
sections, and no teacher's forced daily minimum exceeds 6 of 10 periods, which
leaves the solver far more room than the previous packing did. Task 4 asserts
both the capacity bound and whole-grade ownership so a future edit cannot
silently break either.

**Why every teacher holds more than one subject:** subject purity is not
reachable at this staffing level. HL needs 4 teachers (two 36-period blocks
exceed 60) and MATH 4 more; with NST, SS and the rest the floor is above 20
against 14 staff. The fixture groups subjects per teacher where it can — three
of Carlien's four blocks are Grade 7, and Shane carries Bible across grades —
but it cannot go further.

**Known expected failure:** Task 7 Step 4 leaves
`test_model_solves_the_real_school_and_the_verifier_agrees` failing until Task 8
adds daily bounds and spread. This is stated in both tasks. Do not weaken the
verifier to make it pass early.
