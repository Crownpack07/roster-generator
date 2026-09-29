# Roster — a CAPS-compliant school timetable solver

Builds a primary school's subject timetable for the year. You decide who teaches
what; the software decides when each lesson is taught — producing a clash-free
6-day timetable, or a named explanation of why none exists.

Built for a South African primary school running grades 4–7, three classes per
grade, 14 permanent teachers, and CAPS curriculum requirements.

**Phase 1 (this repository) is the solver core: a Python library plus a CLI.**
Phases 2–4 add a MongoDB-backed API, a React interface, and PDF/Excel exports.

---

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Python 3.12 or newer. The only runtime dependency is Google OR-Tools, which is
a large download (~100 MB) — that is expected.

---

## Produce a timetable

Two steps: solve, then read.

```bash
# Solve. Give it a real budget — see "Why the time limit matters" below.
.venv/bin/python -m roster.cli solve examples/meridian.json --time-limit 150 > roster.json

# Read it, one grid per class.
.venv/bin/python examples/show_roster.py examples/meridian.json roster.json

# Or one grid per teacher, showing their free periods.
.venv/bin/python examples/show_roster.py examples/meridian.json roster.json --teachers
```

The class view looks like this:

```
      Day 1        Day 2        Day 3        Day 4        Day 5        Day 6
  p1  SS/Marius    FAL/Nelmar   LS/Corlie    HL/Christ    STUDY/Karin  NST/Chriss
  p2  FAL/Nelmar   FAL/Nelmar   NST/Chriss   FAL/Nelmar   FAL/Nelmar   LS/Corlie
  ...
  p5  HL/Christ    LS/Corlie    HL/Christ    MATH/Handri  HL/Christ    FAL/Nelmar
  p6  HL/Christ    MATH/Handri  HL/Christ    HL/Christ    BIB/Karin    FAL/Nelmar
```

Afrikaans doubled at p5–p6 on day 1; Maths doubled at p7–p8. Doubles land
wherever they fit rather than being forced into the morning.

### CLI options

| Flag | Default | Notes |
|---|---|---|
| `--time-limit` | 30 | Seconds. See below — the default is too low for a real roster. |
| `--seed` | unset | Fixes CP-SAT's random seed. Does **not** make runs reproducible; see caveats. |
| `--workers` | unset | Search threads. Unset means all cores. |

Exit codes: **0** solved, **1** no timetable (blocked, infeasible or unknown),
**2** the input file is missing or malformed.

### Why the time limit matters

CP-SAT keeps working after it finds an answer, trying to prove that answer is
optimal. It spends its **entire** budget doing so. That has two consequences:

- A bigger limit does not mean "up to" — it means exactly that long.
- A bigger limit buys a **better** timetable. Measured on the example school:

| `--time-limit` | Double periods placed (of 171 possible) |
|---|---|
| 30s (the default) | 125 |
| 150s | **167** |

You build a timetable once a year. Use 150 seconds or more.

---

## Changing the input

`examples/meridian.json` is the whole school in one file. Edit it and re-run.
If your change makes a timetable impossible, the pre-flight checks say so in
plain English before the solver even starts.

### The shape of the file

```jsonc
{
  "grades": [4, 5, 6, 7],
  "sections": ["A", "B", "C"],        // three classes per grade

  "subjects": [
    { "code": "HL",  "displayName": "Afrikaans", "isCore": true,  "isOptional": false },
    { "code": "BIB", "displayName": "Bible Education", "isCore": false, "isOptional": true }
  ],

  "teachers": [
    { "id": "Christa", "name": "Christa", "blockedSlots": [] }
  ],

  "scenario": {
    "caps":     [ { "grade": 4, "subject": "HL", "periods": 12 } ],  // the requirement
    "optional": [ { "grade": 4, "subject": "BIB", "periods": 3 } ],  // available, off by default
    "enabledOptional": ["BIB", "SPT"],                               // which ones actually run
    "overrides": [],                                                 // deliberate CAPS deviations
    "minDoubles": []                                                 // force doubles (see warning)
  },

  "blocks": [
    { "teacherId": "Christa", "grade": 4, "subject": "HL",
      "sections": ["A", "B", "C"], "periodsPerClass": 12 }
  ]
}
```

### The things you will actually want to change

**Reassign a teacher.** Change a block's `teacherId`. One teacher owns a subject
for a whole grade — all three sections — so change it once per block.

**Give a teacher protected time.** Add slots to their `blockedSlots`. A slot is
`day * 10 + period`, zero-based: day 1 period 1 is `0`, day 2 period 1 is `10`,
day 6 period 10 is `59`.

**Switch an optional subject on or off.** Add or remove its code from
`enabledOptional`, and make sure a block exists for it. Grade 4 with *both*
Bible and Sepedi needs 61 periods into 60 slots — pre-flight will tell you, and
you will need an override to make room.

**Deviate from CAPS deliberately.** Add to `overrides`, e.g.
`{"grade": 4, "subject": "SS", "periods": 5}` to teach Social Sciences five
periods instead of six. Every deviation is reported as a warning so it stays a
choice rather than an accident.

**Keep `periodsPerClass` in step.** A block's period count must match what the
curriculum says for that grade and subject, including any override. Pre-flight
rejects a mismatch rather than silently preferring one.

### What pre-flight catches before the solver runs

Each of these names the people, grades and numbers involved:

- a grade whose subjects do not total exactly 60 periods
- a teacher assigned more periods than exist, or than their blocked slots leave
- a teacher forced into more periods per day than a day contains
- a teacher blocked for a whole day who teaches a subject required every day
- a (grade, subject) with no teacher, or with two
- a subject split across teachers instead of owned by one for the whole grade
- a core subject whose period count cannot fit one-to-two per day

---

## Caveats worth knowing before you rely on it

**Solving is hard, and unpredictably so.** The school as configured solves in
about 10 seconds. Small changes can make it unsolvable within any budget tried:
blocking two of one teacher's slots, or enabling Sepedi with two overrides, both
return `unknown`. Blocking one teacher's slots fails where blocking another's
succeeds, **despite identical teaching loads**. Solvability cannot be predicted
from the shape of an assignment.

**`unknown` is not `infeasible`.** `infeasible` means proven impossible — change
something. `unknown` means the solver ran out of time without proving either way
— try again, or try a longer limit. The tool never conflates them.

**Runs are not reproducible, even with `--seed`.** A wall-clock budget stops the
search wherever it happens to be, so two identical commands can return different
but equally valid timetables. Commit the `roster.json` you intend to use.

**Doubles are a preference, not a guarantee.** The solver maximises them; it
does not promise a particular number. Forcing a minimum equal to the theoretical
ceiling makes the problem unsolvable — measured, a minimum of 3, 4 or 5 solves
for a 12-period subject while 6 (the ceiling) does not.

---

## Tests

The solver tests are separated from the rest, because CP-SAT spends its whole
time budget on every solve and together they take about 13 minutes.

```bash
.venv/bin/pytest              # fast unit tests only — about 2 seconds
.venv/bin/pytest -m solver    # the slow solver tests — about 13 minutes
.venv/bin/pytest -m ""        # everything
```

Run the fast set while working. Run the solver set at a phase boundary or before
a release — treat it as an integration suite, not a unit one.

### How the tests are arranged

`roster/verify.py` is a **second, independent implementation** of every
scheduling rule. It re-checks a finished timetable from scratch and imports
neither `ortools` nor `roster/model.py`, enforced by a test that parses its
imports. Every solver test asserts the verifier finds nothing wrong.

That exists because the danger with a constraint solver is not a crash — it is a
wrongly encoded rule being satisfied happily, so the solver returns a timetable
that breaks it while every test passes. Two separate implementations of the rules
cannot easily be wrong in the same way.

---

## Layout

| Path | Holds |
|---|---|
| `roster/domain.py` | Entities and slot arithmetic. No dependencies. |
| `roster/curriculum.py` | Period counts, optional toggles, overrides |
| `roster/allocation.py` | Derived values: filler, doubles ceiling, CAPS deviation |
| `roster/problem.py` | The assembled solver input |
| `roster/preflight.py` | Arithmetic checks with plain-English findings |
| `roster/verify.py` | The independent verifier |
| `roster/model.py` | The CP-SAT constraint model |
| `roster/solve.py` | Orchestration and honest status reporting |
| `roster/diagnose.py` | Turning a solver conflict into English |
| `roster/io.py`, `roster/cli.py` | JSON and the command line |
| `examples/` | A runnable school and a text renderer |
| `docs/superpowers/specs/` | The design, including corrections made under measurement |

Periods are the only unit anywhere in the model. There is no concept of minutes,
because period lengths flex in practice and modelling them buys nothing.

## Running the API

Phase 2 adds a FastAPI service over MongoDB. Install the server extra:

```bash
pip install -e ".[dev,server]"
```

Two environment variables are required and have no defaults:

```bash
export MONGODB_URI="mongodb+srv://..."
export SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Create the first school and its login, then start the server:

```bash
python -m roster.cli create-school \
    --name "Meridian" \
    --email head@meridian.example \
    --password "a real password"

uvicorn roster.api.app:create_app --factory --reload
```

Run exactly one server process (no `uvicorn --workers N`, no overlapping
deploys): the startup sweep fails every queued or running job, on the
assumption that this process is the only one that could have been running
them.

Over plain http locally, set `COOKIE_SECURE=false`, otherwise the login
cookie is marked Secure and browsers (Safari in particular) will not send it
back.

### Solving is a background job

Solving takes 10.5 seconds to several minutes, so `POST /scenarios/{id}/solve`
returns `202` immediately with a solution id, and the client polls
`GET /solutions/{id}`.

The response carries **two** statuses and they never merge:

| Field | Meaning |
|---|---|
| `jobStatus` | `queued` `running` `done` `failed` `cancelled` — did the job execute? |
| `solveStatus` | `optimal` `feasible` `infeasible` `unknown` `blocked` — what did the solver conclude? `null` until `jobStatus` is `done`. |

`failed` means the job crashed. `unknown` means the solver searched and could
neither find a timetable nor prove none exists — a routine outcome for a
perturbed scenario, and **not** the same as `infeasible`.

### Other settings

| Variable | Default |
|---|---|
| `MONGODB_DB` | `roster` |
| `SOLVE_TIME_LIMIT_S` | `150.0` |
| `SOLVE_MAX_WORKERS` | `1` |
| `COOKIE_SECURE` | `true` |
