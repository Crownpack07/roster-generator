# Timetable Generator — Design

**Date:** 2026-09-26
**Status:** Approved for planning

---

## 1. Purpose

A web application that builds a primary school's subject timetable for the year. A
human decides who teaches what; the software decides when each of those lessons is
taught, producing a clash-free 6-day cycle — or a precise explanation of why no
valid timetable exists.

The school is an Afrikaans-medium primary school running grades 4 to 7 with three
classes per grade and 14 permanent teachers. It must comply with CAPS (the South
African national curriculum) period requirements while also offering two subjects
CAPS does not mandate.

**Success looks like:** before the year starts, the timetable person enters who
teaches what, presses Solve, and receives a timetable that is valid by
construction — with an actionable answer when their assignment makes one
impossible.

### Why this is hard

Two properties make this more than a spreadsheet:

1. **Capacity is tight.** 12 classes × 60 slots = 720 teacher-periods of demand
   against 14 × 60 = 840 of capacity, or 86% utilisation before any constraint is
   applied. Infeasibility is a normal outcome, not an edge case.
2. **Core subjects are rigid.** Home Language, First Additional Language and
   Mathematics must appear every day of the cycle and prefer to run as double
   periods. Because one teacher owns a subject across all three classes of a
   grade, a single core block can force that teacher into 6 of 10 periods every
   day.

## 2. Scope

**In scope**

- Curriculum definition: CAPS period counts per grade per subject
- Optional (non-CAPS) subjects, toggled on or off per scenario
- Teacher records with blocked (unavailable) slots
- Assignment editor: teacher ↔ (grade, subject) blocks, with live validation
- Constraint solver producing a complete 6-day-cycle timetable
- Three-layer infeasibility diagnosis
- Per-class, per-teacher and master-grid views
- PDF and Excel export
- Multi-school (multi-tenant) data model; single shared login per school

**Out of scope**

- Learner records or learner-level subject choices. Classes move as whole units.
- Rooms. Teachers are stationary and learners move, so a teacher and their
  classroom are one resource; there is no separate room constraint.
- Mid-year changes, substitute cover, relief timetables
- Wall-clock time. Period lengths may vary and the application never models
  minutes (see §3.2).
- Learner-to-class allocation (a different problem, possibly a later project)

## 3. Domain model

### 3.1 The cycle

- A **cycle** is **6 days** of **10 placeable periods** = **60 slots per class**.
- A slot is a flat index: `slot = day × 10 + period`, 0–59.
- The register period and two 20-minute breaks shorten the day but **consume no
  slot**. They are presentation only and never appear in the model.
- A **double** is two consecutive slots within the same day. Doubles never
  straddle a day boundary — slot 9 (day 0, period 10) and slot 10 (day 1,
  period 1) are not adjacent.

### 3.2 Periods, not hours

**Periods are the only unit of currency in this system.** CAPS requirements are
stored and compared as period counts. Period durations may vary in practice and
are deliberately not modelled: no field, no conversion, no arithmetic. The 6-day
cycle exists precisely to give flexibility in hitting period counts while leaving
teachers some free periods.

### 3.3 Entities

```
School    { id, name, cycleDays: 6, periodsPerDay: 10 }
Teacher   { id, schoolId, name, blockedSlots: [slot] }
Subject   { id, schoolId, code, displayName, isCore, isOptional }
Curriculum{ schoolId, entries: [{ grade, subjectCode, periodsPerClass }] }
Class     { grade, section }            — derived: grades 4–7 × sections A,B,C
Block     { teacherId, grade, subjectCode, classes: [section], periodsPerClass }
```

**`Block` is the central abstraction.** One teacher, one subject, one grade, a set
of classes, N periods per class.

**A block must cover every class of its grade.** The school's rule is that one
teacher owns a subject for a whole grade: if someone teaches Grade 7 English,
they teach it to 7A, 7B and 7C. Splitting a (grade, subject) between two
teachers is a validation error, not a supported configuration (§7.1).

`classes` remains an explicit tuple rather than being implied, for two reasons.
A block stays self-describing — it knows its own total load without consulting
the problem — and the invariant becomes a checked rule with a named error
rather than an assumption buried in the loader.

A block's total load is `periodsPerClass × len(classes)`.

### 3.4 Subjects

`HL` and `FAL` are CAPS roles, not languages: at this school `HL` displays as
"Afrikaans" and `FAL` as "English". Subject codes are display data stored per
school, so a school preferring the Afrikaans codes (WISK, TNW, SW, LOK) changes
one field per subject and no layout.

The subject set differs by grade. Grades 4–6 have `NST` (Natural Sciences &
Technology) and `LS` (Life Skills); at grade 7 these split into `NS` + `TEC` and
`LO` + `CA`. The curriculum is therefore keyed on (grade, subjectCode) and each
grade simply has its own subject list.

### 3.5 Derived values

Never stored; always computed from curriculum plus toggles, so they cannot fall
out of sync:

| Value | Formula |
|---|---|
| Filler periods per class | `60 − (effective curriculum periods) − (active optional periods)`, where *effective* means the CAPS count or its override (§13) |
| Doubles ceiling for a core subject | `n − 6` |
| Teacher load | sum of that teacher's blocks' totals |
| CAPS deviation | assigned periods − CAPS periods, per (grade, subject) |

## 4. Curriculum data

The CAPS column is the **single source of truth** for period counts. It totals
**55 periods** per class per cycle, against a 60-slot grid — leaving 5 slack slots
per class.

### 4.1 CAPS requirements (mandatory)

**Grades 4, 5 and 6** — identical allocation:

| Code | Subject | Periods |
|---|---|---|
| HL | Afrikaans (Home Language) | 12 |
| FAL | English (First Additional Language) | 10 |
| MATH | Mathematics | 12 |
| NST | Natural Sciences & Technology | 7 |
| SS | Social Sciences | 6 |
| LS | Life Skills | 6 |
| SPT | Physical Education | 2 |
| | **Total** | **55** |

**Grade 7:**

| Code | Subject | Periods |
|---|---|---|
| HL | Afrikaans (Home Language) | 10 |
| FAL | English (First Additional Language) | 8 |
| MATH | Mathematics | 9 |
| NS | Natural Sciences | 6 |
| SS | Social Sciences | 6 |
| TEC | Technology | 4 |
| EMS | Economic & Management Sciences | 4 |
| LO | Life Orientation | 4 |
| CA | Creative Arts | 4 |
| | **Total** | **55** |

### 4.2 Optional subjects (non-CAPS, toggleable)

Taken from the per-grade columns of the source spreadsheet, since the CAPS column
records these as zero:

| Code | Subject | Gr 4 | Gr 5 | Gr 6 | Gr 7 |
|---|---|---|---|---|---|
| BIB | Bible Education | 3 | 4 | 3 | 3 |
| SEP | Sepedi | 3 | — | — | — |
| SPT | Physical Education (sport) | — | — | — | 2 |

Note `SPT` is CAPS-mandated for grades 4–6 but optional for grade 7.

### 4.3 Resulting filler per class

With Bible on, Sepedi off, and grade 7 sport on:

| Grade | CAPS | Optional | Filler | Total |
|---|---|---|---|---|
| 4 | 55 | 3 | 2 | 60 |
| 5 | 55 | 4 | 1 | 60 |
| 6 | 55 | 3 | 2 | 60 |
| 7 | 55 | 5 | 0 | 60 |

### 4.4 A known impossibility to report, not hide

**Grade 4 with both Bible and Sepedi needs 61 periods and only 60 exist.**
55 + 3 + 3 = 61. CAPS-as-hard-truth and both optional subjects cannot both hold.
The application must report this as a blocking error naming the exact shortfall,
never silently drop a period. Resolving it requires either turning one optional
subject off or explicitly overriding a CAPS count (see §13).

For reference, the source spreadsheet resolved this by shaving `SS −1` and
`LS −1` while adding `SPT +1` — a net −1 against CAPS. That trade is a decision
for the school to make deliberately, with the deviation visible.

## 5. Two decoupled stages

### 5.1 Assignment (human-owned)

The user assigns a teacher to every (grade, subject) block. The solver treats
these as fixed input and never reassigns.

**A teacher's total teaching load is fully determined by the assignment**, because
every block carries a fixed period count. The solver decides *when* they teach,
never *how much*. Load fairness is therefore an assignment-editor diagnostic, not
a solver objective — the editor is the only place it can be fixed.

**Teachers carry more than one subject, necessarily.** Subject specialisation is
not achievable at this staffing level: HL alone needs 4 teachers and MATH 4
more, which with the remaining subjects puts the floor above 20 against 14
staff. The assignment editor therefore does not attempt to enforce one subject
per teacher; it enforces whole-grade ownership instead.

### 5.2 Scheduling (machine-owned)

Given a valid assignment, place every block's periods into slots. The solver's
sole decision is timing.

## 6. Constraint model

### 6.1 Variables

One boolean family: `x[class][subject][slot]` — "this class studies this subject
in this slot". Approximately 12 × 10 × 60 = **7,200 booleans**. Teacher occupancy
is derived: each (class, subject) pair maps to exactly one block, which names the
teacher.

### 6.2 Hard constraints

| Rule | Encoding |
|---|---|
| Every class slot filled | `sum over subjects of x[c][s][t] == 1` |
| Exact period counts | `sum over slots of x[c][s][t] == periodsPerClass` |
| No teacher in two places | per teacher, per slot: `sum over their blocks' classes <= 1` |
| Blocked slots | the same sum `== 0` |
| Core subject daily presence | per class, core subject, day: `1 <= sum over that day's slots <= 2` |
| Non-core spread | per class, non-core subject, day: `sum over that day <= ceil(n/6)` |
| Doubles bookkeeping | reified `d[c][s][day]` ⇔ that day's two core periods are adjacent |

Filler is modelled as an ordinary subject, which is what makes the
exactly-one-per-slot constraint correct and removes any notion of an empty slot.

### 6.3 The `1 ≤ core per day ≤ 2` bound

The upper bound is load-bearing. Without it nothing prevents a class taking 7 of
its 12 Mathematics periods on one day. Capping at 2 also means **a double is
simply those two periods being adjacent**, which eliminates a whole class of bug:
with three or more periods in a day, adjacent pairs overlap and a naive
"maximise adjacent pairs" objective inflates its own score by clumping. At most
two per day this is impossible by construction.

The counts fit: every core subject lands between 8 and 12 periods, and 1–2 per
day across 6 days spans 6–12.

### 6.4 Non-core spread

Grade 4–6 `NST` has 7 periods and cannot fit "at most one per day" in a 6-day
cycle. The rule is therefore **at most `ceil(n/6)` per day** — one per day for
everything at 6 or below, and `NST` carrying two on exactly one day.

### 6.5 Doubles

For a core subject with `n` periods, constrained to 1–2 per day across 6 days:

- achievable doubles = `n − 6`
- remaining singles = `12 − n`

| Grade | HL | FAL | MATH | Doubles per class |
|---|---|---|---|---|
| 4 | 12 → 6 doubles | 10 → 4 doubles | 12 → 6 doubles | 16 |
| 5 | 12 → 6 | 10 → 4 | 12 → 6 | 16 |
| 6 | 12 → 6 | 10 → 4 | 12 → 6 | 16 |
| 7 | 10 → 4 | 8 → 2 | 9 → 3 | 9 |

`minDoubles` is configurable per (grade, subject) and **defaults to 0** — the
objective earns doubles rather than the constraint demanding them. Setting it to
the `n − 6` ceiling converts a preference into a hard rule and is the fastest
route to an unbuildable timetable.

### 6.6 Objective

**Maximise total doubles.** A single objective, no competing weights, no tuning.
Teacher load fairness is deliberately excluded (§5.1).

### 6.7 An emergent structure, not a rule

Where all three core subjects need a double on the same day, the only way they fit
is a 3×3 rotation: the Home Language teacher takes A, B and C in period-pairs
1-2, 3-4 and 5-6 while Mathematics and FAL rotate the same three pairs in offset
order, filling periods 1–6 of all three classes. This is a **consequence** of the
constraints, not a requirement. Core subjects are free to land anywhere in the
day and no constraint confines them to the morning.

## 7. Diagnostics

Three layers, cheapest and clearest first.

### 7.1 Layer 1 — arithmetic pre-flight

Runs before the solver. Most real failures are counting errors, and arithmetic
explains them better than any solver can.

1. **Coverage** — every (grade, subject, class) has exactly one block; nothing
   unassigned, nothing assigned twice.
2. **Class arithmetic** — each grade totals exactly 60 periods per class. Catches
   §4.4.
3. **Block wholeness** — every block covers all three classes of its grade. A
   (grade, subject) split between two teachers is rejected by name.
4. **Block periods** — a block's stored period count matches the curriculum it
   serves, since the count is stored for the editor and can drift from an
   override.
5. **Teacher capacity** — load + blocked slots ≤ 60. Reports by name:
   *"Christa is assigned 72 periods; only 60 exist (Gr4 Afrikaans 36 + Gr5
   Afrikaans 36)."*
6. **Teacher daily floor** — a core subject with 12 periods across 6 days capped
   at 2 per day is *forced* to 2 every day; across 3 classes that is 6 periods
   daily. Per teacher: `sum over blocks of len(classes) × max(1, n − 10) <= 10`.
   Catches one person holding two 12-period core blocks, which needs 12 periods
   in a 10-period day.
7. **Blocked-day conflict** — a teacher blocked for an entire day while holding a
   subject that must appear every day.

### 7.2 Layer 2 — solver conflict report

Each group of constraints carries an assumption literal. On infeasibility CP-SAT
returns the minimal set of literals that cannot all hold, which is translated
into sentences naming the specific blocks, teachers and grades involved, plus a
ranked list of the smallest changes that would restore feasibility.

Layer 2 exists for structural conflicts arithmetic cannot see — for example:
grade 6's core doubles consume periods 1–6; a teacher's grade 4 block pins her to
periods 7–10; grade 6 `NST` then has fewer reachable slots than it needs.

### 7.3 Layer 3 — honest solver status

Four distinct outcomes, always surfaced as such:

| Status | Meaning |
|---|---|
| **Optimal** | Valid and provably the best possible |
| **Feasible** | Valid, possibly improvable, hit the time limit while optimising |
| **Infeasible** | Proven impossible — re-running will not help |
| **Unknown** | Timed out without proof either way |

Collapsing *infeasible* and *unknown* into "failed" is forbidden; it is the single
change that would make the tool untrustworthy.

### 7.4 Warnings (non-blocking)

CAPS deviation per grade and subject, teacher load imbalance, and which optional
subjects are currently off. These never block a solve — they are the context
needed to know a choice was deliberate.

## 8. Architecture

The solver core is a **pure Python library with no web dependencies**:
`solve(problem) → Schedule | InfeasibilityReport`. It imports nothing from the
web framework, knows nothing about HTTP, and runs from a CLI against a JSON file.
This is the most important boundary in the design: the hard part is testable in
isolation, in milliseconds, without a browser.

| Module | Responsibility | Depends on |
|---|---|---|
| `roster/domain` | Entities. Data only. | — |
| `roster/allocation` | CAPS table, optional toggles, filler sizing, deviation reporting | domain |
| `roster/assignment` | Block validation: coverage, load, blocked-slot conflicts (Layer 1) | domain, allocation |
| `roster/schedule` | CP-SAT model construction, solve, infeasibility diagnosis (Layers 2–3) | domain, allocation |
| `roster/export` | PDF, Excel, CSV renderers | domain |
| `roster/api` | Thin FastAPI layer — no domain logic | all above |
| `web/` | React UI | api, over HTTP only |

**Validation lives in Python only.** The assignment editor needs live feedback as
the user types, and the temptation is to reimplement load-checking in TypeScript.
That guarantees the two drift. The UI calls `POST /validate` on every change; the
payload is a few KB.

**Exports are server-side**, so PDF and Excel share one layout implementation.

**Solve is synchronous with a hard timeout, and writes a `solutions` document.**
At ~7,200 variables it returns well under a second, so a job queue is premature.
Because the result already lands in a collection, moving to background jobs later
changes only the endpoint, never the data model.

**Deployment is one container**: FastAPI serves the built React bundle as static
files. OR-Tools puts the image at roughly 400–500 MB, which rules out hosts with
tight image limits.

## 9. Persistence

**MongoDB Atlas (M0 free tier)**, with `schoolId` on every document from day one.
Retrofitting a tenant scope means touching every query and backfilling every
document; one field added at the start costs nothing.

| Collection | Contents |
|---|---|
| `schools` | name, cycleDays, periodsPerDay |
| `teachers` | schoolId, name, blockedSlots |
| `subjects` | schoolId, code, displayName, isCore, isOptional |
| `curriculum` | schoolId, per (grade, subject) period counts |
| `scenarios` | schoolId, name, optional-subject toggles, **assignments embedded** |
| `solutions` | scenarioId, status, placements, stats, solverVersion, **frozen input snapshot** |

**Assignments are embedded** in the scenario document: roughly 30 per school,
always read together, never queried independently.

**Solutions freeze their input.** A solution stores a copy of exactly what it was
solved from, not a reference. Otherwise editing a teacher's blocked slots
silently invalidates every stored timetable and a "with Sepedi vs without"
comparison becomes untrustworthy. It also makes solves reproducible across solver
changes.

**Scenarios are the comparison mechanism.** Toggling optional subjects produces a
new scenario rather than mutating one, so "Grade 4 with Sepedi" and "without" both
exist, both have solutions, and both can be shown side by side.

**Use PyMongo's native async API (`AsyncMongoClient`, PyMongo ≥ 4.9), not Motor**,
which MongoDB deprecated in 2025. One client instance created in the FastAPI
lifespan handler and reused, because M0 caps connections.

## 10. Authentication

**One login per school** for v1: email plus properly hashed password, session
cookie, `schoolId` resolved from the session and applied to every query. Everyone
at the school shares it. Per-user accounts and roles are deferred until someone
asks.

The data model already carries `schoolId`, so adding a `users` collection scoped
to a school is additive.

## 11. User interface

Five surfaces. Reviewed and approved as mockups at
`https://claude.ai/artifact/GLPv6vG6xeAuHaWLAGdfH2`.

**Visual language:** Newsreader for display type, IBM Plex Sans for interface, IBM
Plex Mono for all numbers and codes, on a warm paper ground (`#F6F4EF`) with deep
teal (`#1F5F5B`) and terracotta accents. English throughout. Subject *names* keep
their real language ("Afrikaans", "Sepedi") because those name the language being
taught.

### 11.1 Assignment editor

Blocks grouped by grade: subject, periods per class, classes, teacher (dropdown),
total. Derived filler rows are visually distinguished as computed rather than
entered. Optional-subject toggles and the scenario selector sit in the toolbar.
Teacher load bars run down the right, over-capacity in red. The pre-flight panel
sits below the table, and the Solve button states the blocking count
("Solve — 1 error to fix") rather than failing after the click.

### 11.2 Class timetable

Days as columns, periods as rows, for one class. **No colour coding** — every cell
is white with the same neutral border, because the school colours printouts by
hand. State is carried by notation instead: `DOUBLE` printed in paired cells, a
dashed outline for study/filler. Doubles render as genuinely merged cells. The
register period and breaks appear as slim bands that visibly are not slots. The
legend lists period counts per subject rather than a colour key.

### 11.3 Teacher timetable

The same grid inverted, showing class and subject per slot. Free periods are a
distinct dotted-outline state with an italic `FREE` label — never blank, because
blank reads as broken. **No colour coding**, as above.

### 11.4 Master grid

One day at a time, classes as rows, periods as columns. Colour coding is retained
here: this is an on-screen problem-spotting view, not a printout. Three
diagnostic cards below it cover CAPS compliance, doubles achieved against the
ceiling, and teacher load range — the last labelled as fixed by the assignment
rather than the solver.

A 12 × 60 full-cycle wall chart is unreadable on screen and is **print-only**.

### 11.5 Infeasibility diagnosis

The Layer 1 summary, the Layer 2 minimal conflicting set presented as numbered
rules joined by "conflicts with", and the ranked smallest ways out, each with an
action. A footer spells out the four solver statuses so *unknown* is never read as
*impossible*.

## 12. Exports

- **Per-class timetable** — PDF and Excel
- **Per-teacher timetable** — PDF and Excel
- **Master grid** — full 60-slot wall chart, print-optimised PDF
- **Diagnostics report** — CAPS deviation and teacher load, Excel

All generated server-side from one layout implementation. Monochrome for the
class and teacher grids, matching §11.2 and §11.3.

## 13. CAPS override

Because §4.4 has no solution within CAPS, the application supports an explicit
per-(grade, subject) override of a CAPS period count. An override:

- requires the user to set it deliberately, never inferred or automatic
- appears in the CAPS deviation report with its signed difference
- is stored on the scenario, so a scenario with overrides is distinguishable from
  one without

This is the mechanism by which a school chooses to fund optional subjects out of
CAPS subjects, with the cost visible.

## 14. Testing

The risk is not a crash; it is a confidently-returned timetable that breaks a
rule. A wrongly-written constraint is satisfied happily, and a test that only
checks "did it return a timetable?" passes.

**The verifier is written before the solver.** `verify(problem, schedule) →
list[Violation]` re-checks every hard rule from scratch: period counts, each
teacher's slots for double-booking, core daily presence, doubles really being
adjacent, blocked slots respected. It shares no code with the CP-SAT model, so a
mistake in the model cannot be mirrored by a matching mistake in the check. Every
solver test asserts `verify(...) == []`. It is far easier to write than the model
and is the operative definition of correct.

Then, in order:

1. **Allocation arithmetic** — filler sizing per grade, the `n − 6` doubles
   ceiling, CAPS deviation, and specifically the Grade 4 + Bible + Sepedi = 61
   case, which must be reported rather than absorbed.
2. **Each pre-flight check** gets two tests: one input that trips it, one that
   does not. Five checks, ten tests.
3. **A golden problem set** from the real school — grades 4–7, the 14 teachers,
   the CAPS table — plus deliberately broken variants, each asserting its
   *specific* diagnosis. This is what stops diagnostics degrading as constraints
   are added.
4. **Generated problems** — random assignments feasible by construction,
   asserting the solver finds a solution and the verifier passes.
5. **API tests stay thin**, since the domain is tested underneath. **UI gets a
   handful of end-to-end paths** — assign, solve, view, export — not a large
   suite. Export tests assert the file generates and contains the expected cell
   count, not pixel comparison.

**Determinism:** CP-SAT searches on multiple threads by default, so the same
problem can return different but equally valid timetables per run, and any test
asserting an exact schedule flakes. Tests fix the random seed and force a single
worker; production uses all threads.

## 15. Deferred

- Per-user accounts and roles
- Background solve jobs
- Interactive drag-to-adjust editing of a solved timetable
- Learner-to-class allocation
- Mid-year amendments and substitute cover
- Importing the existing spreadsheet (the curriculum is small enough to enter
  once; revisit if more schools onboard)

## 16. Key decisions on record

| Decision | Rationale |
|---|---|
| CP-SAT over a hand-written solver | The most valuable output is a *proof* of infeasibility with an explanation; a backtracking search can only ever report "not found in N seconds" |
| CAPS column as source of truth | Chosen over the per-grade columns; makes deviation an explicit, reported choice |
| Periods only, never minutes | Period lengths flex in practice; modelling time adds no value |
| Solver obeys assignment absolutely | Keeps the human in control and makes "your assignment is the problem" a first-class answer |
| Filler as an ordinary subject | Makes exactly-one-per-slot correct and removes the concept of an empty slot |
| A block covers a whole grade | The school's rule: one teacher owns a subject for all three classes of a grade. Enforced, not assumed |
| Teachers hold several subjects | Subject purity would need 20+ staff against 14; it is a staffing limit, not a modelling choice |
| Core capped at 2 periods per day | Prevents clumping and makes "double" unambiguous |
| Load fairness is not a solver objective | Load is fixed by the assignment; the solver cannot change it |
| Monochrome class and teacher grids | The school colours printouts by hand |
| `schoolId` from day one | Retrofitting tenancy is expensive; one field is not |
| PyMongo async, not Motor | Motor deprecated by MongoDB in 2025 |
