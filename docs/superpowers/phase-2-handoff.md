# Handoff: Phase 1 complete → Phase 2

Written at the end of Phase 1's execution so that nothing needed later lives only
in a conversation. The raw execution record is `phase-1-execution-log.md`; this is
the curated version.

**Read this before planning Phase 2.** Several claims in the original spec were
disproved by measurement during Phase 1, and one of them changes Phase 2's
architecture.

---

## 1. Phase 1 status

**Twelve tasks, all implemented, each individually reviewed clean.** 139 tests,
verified after the marker split in both directions:

    pytest            104 passed, 35 deselected, 2.3s
    pytest -m solver   33 passed,  2 skipped,   ~13 min

The two skips are deliberate and visible: two end-to-end tests in
`tests/test_solve.py` call `pytest.skip` with a reason when the solver returns
`unknown` for their scenario, which it does on this hardware. Before that was
made explicit they reported green while asserting nothing about a schedule.

The branch is `worktree-solver-core`, based on `2eefa55`.

It produces a real, verified timetable for the real school: 720 placements, 167
of 171 possible double periods, zero teacher clashes, core subjects on every day
of the cycle, verifier clean.

### Outstanding, and the one thing to do first

**The whole-branch review never completed.** It was dispatched twice on the most
capable model and killed both times by account rate limits, mid-analysis. Every
*task* passed its own scoped review, but the broad pass — the one that catches
cross-task problems — did not finish.

That matters because the one genuine cross-task regression in the branch was
found by a full-suite run rather than by any task's review: `roster/__init__.py`
exporting the `verify` function rebound the `roster.verify` attribute from the
submodule to the function, silently disabling the test that asserts the verifier
imports neither `ortools` nor `roster/model.py`. That guard is the load-bearing
claim of the whole design and it was inert for several commits. Fixed, but it
demonstrates the class of defect still unaudited.

**Recommendation: run the whole-branch review before starting Phase 2.** Its
unfinished output noted two leads worth chasing: an "enforcement-literal
hypothesis" it had disproved by measurement (10.53s vs 10.46s), and a
"missing-subject-row defect" it was confirming end to end when it died. Neither
was ever reported. Those words are all that survive of it.

---

## 2. Spec claims that measurement disproved

> **Superseded in part, 2026-10-01.** Commit 6dcdd52 (search an unguarded model
> on at least four workers) overturned the solver-hardness findings in 2.1, 2.2
> and 3 below. Every case in those tables, including Karin's blocked slots and
> Sepedi with overrides, now finds a timetable in about 0.3s and reaches 171/171
> doubles; 30s is enough for 171/171 on 14 cores. `unknown` must still never be
> shown as "impossible". The text below is kept as the record of what Phase 1
> measured at the time.

Three claims in `specs/2026-09-26-timetable-generator-design.md` were written
during design, never tested, and turned out false. All three are corrected in the
spec, but the corrections matter enough to restate.

### 2.1 Solving is not sub-second — and Phase 2's architecture depends on this

The spec originally said solving "returns well under a second, so a job queue is
premature." Measured:

| Scenario | Result |
|---|---|
| The school as configured | first solution **10.5s**; optimality unproven at 200s |
| One teacher's two slots blocked | **no solution at all** within 200s |
| Sepedi enabled with two CAPS overrides | **no solution at all** within 200s |

**A synchronous HTTP request cannot carry this work.** Phase 2 must put solving
behind a background job with polling from its first commit. The "scale-later
seam" the spec originally deferred is needed at the start. Freezing the input
snapshot on the `solutions` document — already in the design — is what makes this
straightforward: the job owns a snapshot, the endpoint only reads status.

### 2.2 Solver hardness is a known, accepted property

The model solves the school as configured and becomes unreliable under small
perturbations. Blocking *Karin's* slots fails where blocking *Shane's* succeeds
**despite identical teaching loads and both holding only non-core subjects**.
Solvability cannot be predicted from an assignment's shape.

The user was shown this and decided explicitly to accept it and finish the phase,
scoping solver-performance work (search hints, redundant constraints, symmetry
breaking across a grade's three identical sections) as separate work.

**Two consequences Phase 2 and 3 must honour:**

- `unknown` is a routine outcome for a perturbed scenario and must **never** be
  rendered as "impossible". Spec 7.3 forbids conflating them and users are told
  to trust the distinction.
- The blocked-slot feature (spec 7.1, 11.1) can leave a school with no answer.
  The UI must say so plainly rather than appear broken.

### 2.3 A fixed seed does not make runs reproducible

Under a wall-clock limit the search stops wherever it happens to be, so identical
seeds return different schedules. Tests therefore assert *properties* of a
schedule, never an exact schedule. Anything in Phase 2 that caches or compares
solutions must not assume determinism.

### 2.4 The conflict report is coarser than promised

Spec 7.2 originally promised "the minimal set of literals that cannot all hold".
`roster/model.py` registers **one assumption literal per rule category — seven in
total**, each gating its whole category across every class, so there is almost
nothing for a core to shrink to. An infeasible scenario whose sole cause was one
setting returned **all seven** groups.

`explain()` now flags that degenerate case honestly. Narrowing it needs either
iterative re-solving (up to seven extra solves) or finer-grained literals — real
work, deliberately unscoped. **Phase 3's diagnosis screen should not promise
precision the layer cannot deliver.**

---

## 3. Two production settings that are deliberate

**`linearization_level = 0`** is set in both `solve()` and the tests. CP-SAT's
linear relaxation costs 7–18× on this model: at its default the school needs ~69s
to a first solution, so a 30s limit would report `unknown` for the primary use
case. The reasoning and measurements are in a comment in `roster/solve.py`.

**`solve()`'s default `time_limit_s=30.0` yields a visibly worse timetable** than
a longer run — 125 of 171 doubles against 167 at 150s. This was accepted because
doubles are a *soft* objective, `verify()` still passes, and the CLI exposes
`--time-limit` while printing both numbers so nothing is concealed. **Revisit when
Phase 2 moves solving to a background job**, where a much longer default costs
nothing. That is the single most valuable easy win available to Phase 2.

---

## 4. Deferred findings, for the whole-branch review to triage

Twenty-one Minor findings were recorded and deliberately not fixed. The six worth
attention first:

1. **`tests/test_solve.py`: two of twelve tests are inert on this machine** —
   they `pytest.skip` because the solver returns `unknown` for a blocked-slot
   scenario and for Sepedi-with-overrides. Visible now rather than silently
   green, but that is 10-of-12 effective end-to-end coverage.
2. **`tests/test_model.py` still carries 45s/60s/120s limits** where every other
   module was trimmed to 25–30s. About 225s of pure waiting for no assertion
   benefit.
3. **`test_block_periods_match_the_curriculum_demand` is tautological** — the
   fixture sets period counts *from* `demand()` and the test re-derives them from
   `demand()`, so it can only fail if that function is non-deterministic.
4. **`tests/test_diagnose.py`'s non-degenerate branch never executes**, because
   every infeasible fixture returns all seven rule groups. The test cannot
   distinguish "note added only when degenerate" from "note added always".
5. **`roster/solve.py` maps `MODEL_INVALID` to `UNKNOWN`**, folding a
   constraint-construction bug into the same status an ordinary timeout produces.
   A reviewer suggested raising instead.
6. **The five `SolveStatus` meanings are documented in the plan and test
   docstrings, not in `solve.py`** where the never-merge-them invariant is
   actually enforced.

The remaining fifteen are in `phase-1-execution-log.md` (search
`minor (deferred)`): unused imports resolved by a later task, a redundant
predicate shared by `block_for` and `coverage_problems`, inconsistent defensive
lookups in `verify.py`, per-day count logic duplicated three ways, and similar.

---

## 5. Process lessons that cost real time

Recorded because they are cheap to repeat and expensive to rediscover.

**Separate solver tests from unit tests.** Done at the end of Phase 1, and it
should have been done at the start. `pytest` now runs 104 unit tests in ~2
seconds; `pytest -m solver` runs the 35 slow ones. Before the split, a full run
took 13 minutes and **that single fact caused most of the execution failures
below.** Mark anything that drives CP-SAT with `@pytest.mark.solver`.

**A long test run silently kills a subagent's turn.** The Bash tool defaults to a
120-second timeout and moves anything longer to the background, so an agent
running a multi-minute pytest loses its result mid-turn. Five agents died this
way before the cause was identified. **Pass an explicit `timeout` of `600000` on
any pytest call.** Background bash, by contrast, survives turn boundaries — it is
the reliable place for long runs.

**Never run the controller's suite concurrently with an implementer.** Two pytest
processes contend for CPU, and worse, a suite started before an edit lands tests
a mix of old and new code. A green result there means nothing.

**A measurement that mirrors your expectation is not a measurement.** This caused
four separate plan defects. Each time, an assumption was "validated" against
inputs chosen to match it:

- A test helper's daily caps were checked; teacher clashes were not — and the
  helper produced 232 clashes.
- A `min_doubles` ceiling was arithmetically right but unreachable in practice.
- A time limit was set from a 3× margin over the *baseline* scenario, and two
  harder scenarios then failed at any budget.
- A generator was measured with its non-core draws maxed out, so it never
  produced the all-zeros draw that made 23.4% of its output invalid.

The habit that works: measure the configuration you expect **and** its opposite,
and sample the range rather than a convenient point.

**Ask an implementer for judgement, not just compliance.** The most valuable
findings in Phase 1 came from agents volunteering things no test caught — a
degenerate UNSAT core that satisfied every assertion, a `BLOCKED` rate that
meant 37% of property-test examples never reached the solver. Both were reported
unprompted because the dispatch asked for an opinion.

---

## 6. What Phase 2 needs decided before planning

- **Background solving is not optional** (see 2.1). Job model, polling endpoint,
  and where the worker runs.
- **Raise the default time limit** once solving is asynchronous (see 3).
- **MongoDB Atlas credentials.** Nothing in Phase 1 touches a database, so the
  connection string, and whether to test against a local `mongod`, a container,
  or `mongomock`, is an open question. Atlas M0 caps connections, which is why
  the spec calls for one client created in the FastAPI lifespan handler.
- **`schoolId` on every document from day one**, per spec 9 — cheap now,
  expensive to retrofit.
- **PyMongo's native async API, not Motor**, which MongoDB deprecated in 2025.
