# Persistence and API — Design (Phase 2 of 4)

**Phase 1** built a pure-Python solver core: `solve(problem) -> SolveResult`, no web
framework, no database, no HTTP. **Phase 2** puts that core behind MongoDB and a
FastAPI service so that Phase 3's React UI has a finished backend to build against.

**Read `../phase-2-handoff.md` first.** Three claims in the Phase 1 spec were
disproved by measurement, and one of them dictates this phase's architecture.

- Phase 1 spec: `2026-09-26-timetable-generator-design.md` — its sections are cited
  as **P1 §N**. A bare **§N** means a section of *this* document.
- Phase 1 plan: `../plans/2026-09-26-solver-core.md`
- Phase 1 handoff: `../phase-2-handoff.md`

---

## 1. Purpose and success criteria

Phase 3 must be able to build the five UI surfaces (P1 §11) entirely over HTTP,
without reaching past the API into the solver library.

Phase 2 is done when:

1. Every entity in P1 §9 can be created, read, updated and deleted through the API,
   scoped to a school.
2. A scenario can be assembled into a `Problem`, validated, and solved as a
   background job whose progress is pollable.
3. A solution stores the exact input it was solved from.
4. The solver core is provably still free of web and database dependencies.

### Assumptions, recorded so they can be corrected

- One school in practice, multi-tenant in shape.
- The approved mockups (P1 §11) define the endpoint surface.
- Phase 4 exports (P1 §12) are out of scope. No deployment work in this phase.

---

## 2. Scope

**In scope**

- MongoDB document model, indexes, and a repository layer
- Scenario assembly into a `roster.problem.Problem`
- `POST /validate` — arithmetic pre-flight only, for live editor feedback
- Background solve jobs with polling
- Solutions with a frozen input snapshot
- Authentication: one login per school (P1 §10), session cookie, tenant scoping
- CLI bootstrap for the first school and user

**Out of scope**

- PDF / Excel / CSV export (Phase 4, P1 §12)
- React UI (Phase 3)
- Deployment, container build, hosting
- Per-user accounts and roles (P1 §10 defers these)
- Login rate limiting
- Solver performance work — search hints, redundant constraints, symmetry
  breaking (explicitly scoped as separate work in the handoff)

---

## 3. What Phase 1 binds

These are measured facts, not preferences. Each one constrains a decision below.

### 3.1 Solving cannot happen in a request

| Scenario | Measured |
|---|---|
| The school as configured | first solution **10.5s**; optimality unproven at 200s |
| One teacher's two slots blocked | **no solution** within 200s |
| Sepedi enabled with two CAPS overrides | **no solution** within 200s |

An earlier draft of P1 §8 claimed solving "returns well under a second, so a job
queue is premature". That was untested and false. **Background solving is a
starting constraint of this phase, not a later optimisation.**

### 3.2 `unknown` is routine, and never means `infeasible`

The model becomes unreliable under small perturbations: blocking Karin's slots
fails where blocking Shane's succeeds, despite identical teaching loads and both
holding only non-core subjects. Solvability is not predictable from an
assignment's shape. P1 §7.3 forbids conflating the two statuses, and the API must
carry the distinction intact to the UI. See §5.2 below, which extends the same
rule to the job layer.

### 3.3 Solutions must freeze their input

Without it, editing a teacher's blocked slots silently invalidates every stored
timetable, and a "with Sepedi vs without" comparison becomes untrustworthy (P1 §9).

### 3.4 Runs are not reproducible

A wall-clock limit stops the search wherever it happens to be, so a fixed seed
does **not** yield the same schedule twice. Nothing in this phase may cache,
deduplicate or compare solutions on the assumption of determinism.

### 3.5 `schoolId` on every document from day one

Retrofitting a tenant scope means touching every query and backfilling every
document (P1 §9).

---

## 4. Module layout and the boundary that must not break

P1 §8's table places the web layer at `roster/api`. Phase 2 follows that, adding two
sibling packages:

| Package | Responsibility | Depends on |
|---|---|---|
| `roster/domain`, `curriculum`, `allocation`, `problem`, `preflight`, `model`, `diagnose`, `solve`, `verify`, `io` | Phase 1 core. **Unchanged.** | — |
| `roster/store/` | Documents, codecs, repositories, index setup | `pymongo`, core |
| `roster/jobs/` | Solve job, process pool, lifecycle | `pymongo`, core |
| `roster/api/` | App, routers, schemas, auth, dependencies | `fastapi`, store, jobs |

### 4.1 Two guards with tests behind them

**`roster/__init__.py` must not import `store`, `jobs` or `api`.**

This is not stylistic. Phase 1's single cross-task regression was
`roster/__init__.py` exporting the `verify` *function*, which rebound the
`roster.verify` attribute away from the submodule and silently disabled the test
asserting the verifier imports neither `ortools` nor `roster/model.py`. That
guard is the load-bearing claim of the whole design and it was inert for several
commits. The same mechanism would let `fastapi` or `pymongo` leak into the pure
core unnoticed.

**The existing independence test extends to the new layers.** `roster.solve`,
`roster.model` and `roster.verify` must import neither `fastapi` nor `pymongo`.
This is the cheapest available audit of precisely the defect class that Phase 1's
unfinished whole-branch review was meant to catch.

### 4.2 Pydantic lives only at the HTTP edge

Domain dataclasses never acquire web or BSON concerns. `roster.io`'s
`problem_to_dict` / `problem_from_dict` / `result_to_dict` are the bridge in both
directions. They already emit camelCase, they are already tested, and they are
already the CLI's format — so the wire format, the CLI format and the frozen
snapshot format are one thing that cannot drift apart.

---

## 5. The solve job

### 5.1 One collection, not two

P1 §8 says solve writes a `solutions` document; P1 §9 says solutions freeze their
input. Rather than a separate `solveJobs` collection requiring a cross-document
consistency dance, **the solution document is the job record from the moment the
solve is requested**, and fills in as the job progresses.

### 5.2 Two status fields, never merged

| Field | Values | Answers |
|---|---|---|
| `jobStatus` | `queued` `running` `done` `failed` `cancelled` | Did the job execute? |
| `solveStatus` | `optimal` `feasible` `infeasible` `unknown` `blocked` | What did the solver conclude? |

`solveStatus` is `null` unless `jobStatus == done`.

**A crashed job is `failed`, never `unknown`.** A solve that exhausted its clock
is `done` + `unknown`. Collapsing those would repeat at the job layer exactly the
sin P1 §7.3 forbids at the solver layer — and this time the UI would inherit it.
`failed` means "we do not know because we broke"; `unknown` means "the solver
searched and could neither find nor disprove".

### 5.3 Flow

1. `POST /scenarios/{id}/solve` assembles the `Problem`, freezes
   `problem_to_dict(problem)` onto a new solution document as `inputSnapshot`,
   sets `jobStatus=queued`, and returns `202` with the document id.
   **The snapshot is frozen at request time**, so edits made while the job waits
   in the queue cannot change what is solved.
2. The job is submitted to a `ProcessPoolExecutor`. `jobStatus=running` when it
   starts.
3. On success the parent writes `jobStatus=done`, `solveStatus`, `placements`,
   `stats`, `findings`, `conflict`, `solverVersion`, `finishedAt`.
4. On exception the parent writes `jobStatus=failed` and an error message.
5. Polling is `GET /solutions/{id}`.

### 5.4 The worker process never touches MongoDB

The child receives the snapshot **dict**, calls `problem_from_dict` →
`solve(...)` → `result_to_dict`, and returns a dict. The parent performs every
database write.

Three reasons, all load-bearing:

- **Atlas M0 caps connections** (P1 §9). A pool of database-connecting children
  would spend them for nothing.
- **It keeps the pure core pure.** The child imports `roster` and nothing else.
- Dicts are unambiguously picklable across the process boundary.

### 5.5 Pool of one

CP-SAT saturates whatever cores it is given, and Phase 1 ran production with
CP-SAT's default worker count. One school does not need concurrent solves, so
`max_workers=1` serialises them and lets CP-SAT have the machine. Configurable
by environment variable.

### 5.6 Default time limit: 150 seconds

Phase 1's `solve()` defaults to `time_limit_s=30.0`, which yields a visibly worse
timetable: **125 of 171 possible doubles against 167 at 150s**. That default
existed only because a synchronous request could not wait. Behind a polling job
the wait costs a user nothing but a progress indicator, so the API defaults to
**150s**, overridable per request.

`linearization_level = 0` stays as Phase 1 set it. CP-SAT's linear relaxation
costs 7–18x on this model; at its default the school needs ~69s to a first
solution.

### 5.7 Restart recovery

The process pool dies with the container, so on lifespan startup any document
still `queued` or `running` is orphaned by definition. Startup sweeps them to
`jobStatus=failed` with reason "server restarted during solve". A one-container
deployment needs no heartbeat.

### 5.8 Cancellation, stated honestly

Cancellation is supported **while `queued`**. A running CP-SAT solve cannot be
interrupted without killing the pool process, so v1 does not offer it — and does
not need to, because the time limit means every solve self-terminates. This
limitation is written down rather than papered over with a cancel button that
silently does nothing.

---

## 6. Persistence

### 6.1 Collections

Every document carries `schoolId` (P1 §9). `users` and the job fields on `solutions`
are additions to P1 §9's table.

| Collection | Fields |
|---|---|
| `schools` | `name`, `cycleDays`, `periodsPerDay` |
| `users` | `schoolId`, `email`, `passwordHash` |
| `teachers` | `schoolId`, `name`, `blockedSlots` |
| `subjects` | `schoolId`, `code`, `displayName`, `isCore`, `isOptional` |
| `curriculum` | `schoolId`, `grade`, `subjectCode`, `periods`, `kind` |
| `scenarios` | `schoolId`, `name`, `enabledOptional`, `overrides`, `minDoubles`, `blocks` (embedded) |
| `solutions` | `schoolId`, `scenarioId`, `jobStatus`, `solveStatus`, `inputSnapshot`, `placements`, `stats`, `findings`, `conflict`, `solverVersion`, timestamps, `error` |

**`curriculum` needs a `kind` discriminator (`caps` | `optional`).** Phase 1's
`Scenario` holds `caps` and `optional` as two separate `Curriculum` objects, so a
single flat collection cannot represent them without it. This is a mapping detail
the Phase 1 spec's §9 does not mention.

**Assignments stay embedded in the scenario** (P1 §9): roughly 30 per school, always
read together, never queried independently.

### 6.2 Indexes

- `schoolId`-first compound index on every collection
- unique `(schoolId, code)` on `subjects`
- unique `(schoolId, grade, subjectCode, kind)` on `curriculum`
- unique `(schoolId, email)` on `users`
- `(scenarioId, createdAt)` on `solutions`

### 6.3 Driver: synchronous PyMongo

P1 §9 originally called for PyMongo's native async API (`AsyncMongoClient`). **This
phase uses the synchronous `MongoClient` instead**, and endpoints that touch
MongoDB are declared `def` so FastAPI runs them in its threadpool, never blocking
the event loop.

Reasoning, because this reverses a written decision:

- P1 §16's decision on record is *"PyMongo async, **not Motor** — Motor deprecated by
  MongoDB in 2025."* The thing being avoided is Motor. Synchronous PyMongo avoids
  it equally.
- **mongomock does not support `AsyncMongoClient`.** [mongomock#916] is open and
  unimplemented; mongomock mocks the synchronous client only, and its async path
  historically ran through `mongomock_motor` — the very library P1 §9 rules out. The
  chosen test strategy (§9 below) and `AsyncMongoClient` are not a combination
  that exists.
- The expensive work is already in a process pool, so async database I/O buys
  little for one school and a few KB of documents.

**One `MongoClient` instance is created in the FastAPI lifespan handler and
reused**, because M0 caps connections (P1 §9).

Cost, recorded: if a later phase needs genuine async database concurrency, that
is a migration.

[mongomock#916]: https://github.com/mongomock/mongomock/issues/916

### 6.4 No transactions

Every write in this phase is a single-document update, which MongoDB makes atomic
on its own. Nothing here requires a multi-document transaction, which also keeps
the design within what mongomock can represent.

---

## 7. API

### 7.1 Shape: scenario aggregate plus granular CRUD

Granular REST over the collections serves the editors; one aggregate endpoint
serves assembly.

**`GET /scenarios/{id}/problem` returns the fully assembled `Problem` in
`roster.io` format.** Assembly happens server-side, in exactly one function, and
that same function is what the solve job uses. The UI therefore cannot assemble a
subtly different problem than the solver sees. P1 §8 is explicit that validation
duplicated in TypeScript is guaranteed to drift; assembly duplicated in
TypeScript is the same trap one layer down.

### 7.2 Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/login` | email + password, sets session cookie |
| `POST` | `/auth/logout` | clears the cookie |
| `GET` | `/auth/me` | current school and user |
| `GET`/`PATCH` | `/school` | the session's school |
| CRUD | `/teachers`, `/subjects`, `/curriculum` | entity editors |
| CRUD | `/scenarios` | including embedded blocks |
| `GET` | `/scenarios/{id}/problem` | assembled `Problem` |
| `POST` | `/scenarios/{id}/validate` | pre-flight findings only |
| `POST` | `/scenarios/{id}/solve` | enqueue; `202` + solution id |
| `GET` | `/scenarios/{id}/solutions` | history for comparison (P1 §9) |
| `GET` | `/solutions/{id}` | poll status and read the result |
| `POST` | `/solutions/{id}/cancel` | cancel while queued (§5.8) |

### 7.3 `POST /validate` runs pre-flight only

It assembles the `Problem` and calls `preflight()` — pure arithmetic, no CP-SAT,
milliseconds. This is where the assignment editor's live feedback comes from
(P1 §8), and why `/solve` does not need to short-circuit blocked problems in the
request: the UI already knows.

### 7.4 Errors

- `400` malformed request body
- `401` no or invalid session
- `404` id not found **within the session's school** — a document belonging to
  another school is indistinguishable from one that does not exist
- `409` unique-index violation (duplicate subject code, email)
- `422` a scenario that cannot be assembled into a `Problem` at all

A pre-flight finding is **not** an error. `/validate` returns `200` with findings,
and a blocked solve is a `200` solution document with `solveStatus=blocked`.
Findings are answers, not failures.

---

## 8. Authentication and tenancy

**One login per school** (P1 §10): email plus hashed password, session cookie,
`schoolId` resolved from the session and applied to every query.

- **Hashing: `argon2-cffi` (Argon2id), used directly.** Not `passlib`, whose last
  release was 2020 and which is effectively unmaintained; a dead dependency is
  the wrong trade for a password hash.
- **Session: a signed cookie** (`itsdangerous`) carrying `{schoolId, userId,
  issuedAt}`, `HttpOnly`, `SameSite=Lax`, `Secure` in production, with a maximum
  age. Stateless: no session collection and no extra read per request.
  **Cost, recorded:** a session cannot be revoked server-side before it expires.
  Acceptable for one shared school login; revisit with per-user accounts.
- **`SESSION_SECRET` is required and the app refuses to start without it.** Never
  a baked-in default, because a default that works in development is a
  forged-session hole in production.

### 8.1 Tenancy is structural, not disciplined

**Every repository method takes `school_id` as a required positional parameter.**
There is no overload that omits it and no module-level default. A query that
forgets its tenant scope does not type-check, rather than passing review and
leaking another school's data.

### 8.2 Bootstrap

The first school and user are created by extending the existing CLI
(`python -m roster.cli`), not by a hand-run snippet. A documented command is
reproducible; a snippet in a chat log is not.

---

## 9. Testing

Phase 1's lesson was not about coverage. It was that **a measurement mirroring
your expectation is not a measurement**, and that a slow suite corrupts every
process built on it.

| Layer | How | Speed |
|---|---|---|
| Store | mongomock, real repository code | ms |
| API | `TestClient` + mongomock + injected fake solver | ms |
| Job lifecycle | fake solve function, including orphan recovery | ms |
| End-to-end real solve | **one** test, `@pytest.mark.solver` | ~150s |
| Boundaries | pure core imports no `fastapi`/`pymongo`; repositories reject a missing `school_id` | ms |

### 9.1 Marker discipline from the first commit

Phase 1 split solver tests from unit tests at the *end*, and the 13-minute cycle
that preceded the split caused most of its execution failures. Phase 2 starts
split. Anything that drives CP-SAT carries `@pytest.mark.solver`; the default
`pytest` run excludes them. mongomock runs in-process, so store and API tests
need no marker of their own.

The Phase 1 baseline to preserve: `pytest` → **104 passed in ~1.3s**.

### 9.2 Every pytest invocation passes an explicit timeout

The Bash tool defaults to a 120-second timeout and backgrounds anything longer,
which silently killed five Phase 1 agents mid-turn. Every pytest call in the
implementation plan carries `timeout=600000`.

### 9.3 What tests must not assume

- **Not determinism** (§3.4). Assert properties of a schedule, never an exact
  schedule.
- **Not that `unknown` is failure** (§3.2). A test asserting a perturbed scenario
  is solvable is asserting something measurement has already disproved.

### 9.4 The limitation of the mongomock choice, recorded

mongomock reimplements MongoDB. Its unique-index enforcement and error semantics
are not Atlas's. The duplicate-email and duplicate-subject-code tests therefore
prove that **our code issues the right operations**, not that Atlas rejects them
identically. The mitigation is a smoke check against a real cluster — see §11.

---

## 10. Configuration

| Variable | Purpose | Default |
|---|---|---|
| `MONGODB_URI` | Connection string | none; required to serve |
| `MONGODB_DB` | Database name | `roster` |
| `SESSION_SECRET` | Cookie signing key | none; **required, no default** |
| `SOLVE_TIME_LIMIT_S` | Default solve budget | `150.0` |
| `SOLVE_MAX_WORKERS` | Process pool size | `1` |
| `COOKIE_SECURE` | `Secure` flag on the session cookie | `true` |

No MongoDB instance is needed to build or test Phase 2 — mongomock covers the
test suite, and `MONGODB_URI` is read only when actually serving.

---

## 11. Phase 2 exit items

Carried forward explicitly so they are not lost a second time.

1. **The Phase 1 whole-branch review.** Dispatched twice, killed by rate limits
   both times, deliberately deferred to the merge gate. Its unfinished output
   noted two leads that were never reported: an "enforcement-literal hypothesis"
   it had disproved by measurement (10.53s vs 10.46s), and a
   "missing-subject-row defect" it was confirming when it died.
2. **Provision Atlas and run the smoke check** (§9.4) — the one thing mongomock
   structurally cannot prove.
3. **Triage the 21 deferred Phase 1 findings.** Six are listed in the handoff's
   P1 §4; the rest are in `phase-1-execution-log.md` under `minor (deferred)`.

---

## 12. Key decisions on record

| Decision | Rationale |
|---|---|
| Background solve job from the first commit | Measured 10.5s–200s+; a request cannot carry it (§3.1) |
| Solution document *is* the job record | Avoids a two-collection consistency dance; P1 §8 already says solve writes a solutions document |
| `jobStatus` and `solveStatus` kept separate | "We broke" and "the solver could not decide" are different answers; merging them repeats P1 §7.3's forbidden collapse |
| Worker process never touches MongoDB | M0 connection cap; keeps the pure core pure |
| Pool of one | CP-SAT saturates its cores; one school needs no concurrent solves |
| Default time limit raised 30s → 150s | 167 of 171 doubles against 125; the old default only existed to fit a request |
| No cancel for a running solve | Cannot interrupt CP-SAT without killing the process; the time limit bounds it anyway |
| Synchronous PyMongo, not `AsyncMongoClient` | mongomock cannot mock the async client; P1 §16's real decision was to avoid Motor, which this also does |
| mongomock over a real mongod in tests | Chosen for speed and zero infrastructure, with §9.4's limitation recorded and §11.2 as the mitigation |
| `argon2-cffi` over `passlib` | passlib unmaintained since 2020 |
| `SESSION_SECRET` required, no default | A working default is a forged-session hole |
| `school_id` a required repository parameter | Makes tenant scoping a type error to omit, not a review item to remember |
| Server-side scenario assembly | One assembly function for UI and solver; duplicating it in TypeScript would drift (P1 §8) |
| `roster/__init__.py` imports no web or DB module | Phase 1's only cross-task regression was exactly this mechanism (§4.1) |
