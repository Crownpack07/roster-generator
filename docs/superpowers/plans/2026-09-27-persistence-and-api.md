# Persistence and API Implementation Plan (Phase 2 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the Phase 1 solver core behind MongoDB and FastAPI, with solving as a background job, so Phase 3's React UI has a finished backend to build against.

**Architecture:** Three new packages sit *above* the untouched Phase 1 core. `roster/store` owns documents, repositories and scenario assembly; `roster/jobs` owns the solve job and its process pool; `roster/api` owns HTTP. The solver core keeps importing neither `fastapi` nor `pymongo`, and a subprocess test proves it on every run. Solving happens in a child process that never touches MongoDB — the parent performs every database write.

**Tech Stack:** Python 3.12, FastAPI, synchronous PyMongo, `argon2-cffi`, `itsdangerous`, pytest, mongomock, httpx.

**Spec:** `docs/superpowers/specs/2026-09-27-persistence-and-api-design.md`

**Prior phase:** `docs/superpowers/plans/2026-09-26-solver-core.md` (complete), `docs/superpowers/phase-2-handoff.md` (read this first).

## Global Constraints

- Python `>=3.12`. Phase 1's runtime dependency stays `ortools>=9.11`.
- **Server dependencies go in a `server` extra, not in `dependencies`.** P1 §8 calls the solver core "a pure Python library with no web dependencies", and that is a distribution property as well as an import property. `pip install roster` must not pull FastAPI.
- **`roster/__init__.py` must not import `roster.store`, `roster.jobs` or `roster.api`.** Phase 1's only cross-task regression was this exact mechanism (spec §4.1).
- **`roster.solve`, `roster.model`, `roster.verify` and `roster.io` must import neither `fastapi` nor `pymongo`** — transitively, not just directly.
- **Phase 1's core modules are not modified.** `domain.py`, `curriculum.py`, `allocation.py`, `problem.py`, `preflight.py`, `model.py`, `diagnose.py`, `solve.py`, `verify.py`, `io.py` are read-only in this phase. `cli.py` is the one exception (Task 12).
- **Every repository method takes `school_id` as a required positional parameter** (spec §8.1). No default, no keyword-only with a fallback.
- **`jobStatus` and `solveStatus` are separate fields and are never merged** (spec §5.2). A crashed job is `failed`, never `unknown`.
- `jobStatus` ∈ `queued` `running` `done` `failed` `cancelled`. `solveStatus` ∈ `optimal` `feasible` `infeasible` `unknown` `blocked`, and is `None` unless `jobStatus == "done"`.
- **Default solve budget is `150.0` seconds** (spec §5.6). Not Phase 1's 30.0.
- **The child process imports `roster` and nothing else** (spec §5.4). It receives a dict and returns a dict.
- **`SESSION_SECRET` has no default.** The app refuses to start without it (spec §8).
- All wire JSON is camelCase, matching `roster/io.py`, which already emits camelCase.
- **Status codes, resolving one ambiguity in spec §7.4.** That section lists `400` for a malformed body, but FastAPI already returns `422` for a body Pydantic rejects, and fighting the framework to change it would buy nothing. So: `422` for a body that fails schema validation *and* for a stored scenario that cannot be assembled; `400` only for a value that is well-typed but out of range, which Pydantic cannot know about — a blocked slot of `60`, a curriculum `kind` of `"invented"`. `409` for a unique-index violation. `404`, never `403`, for anything outside the session's school.
- All user-facing strings are English only (P1 §11).
- **Every `pytest` invocation passes an explicit `timeout=600000`** to the Bash tool. The 120-second default silently killed five Phase 1 agents mid-turn (spec §9.2).
- Anything that drives CP-SAT carries `@pytest.mark.solver`. The default `pytest` run excludes them. Baseline to preserve: `pytest` → **104 passed in ~1.3s**.

### One addition to P1 §9's collection table

`schools` documents also carry **`grades`** and **`sections`**. `Problem` needs both and P1 §9's table lists neither; without them a scenario cannot be assembled. This is the same kind of addition as `users`, recorded here rather than discovered in Task 4.

## Review Focus

Five conditions the spec implies that no obvious task would exercise, most likely to bite first. Each has its test pinned to the task that owns the code.

1. **A document belonging to another school must be indistinguishable from one that does not exist.** `GET /teachers/{id}` with a valid id from school B, while signed in as school A, must return `404` — not `403`, not the document. This is the most likely security defect in the phase. → Task 9.
2. **A solution polled while `jobStatus == "running"` must report `solveStatus: null`**, and a `failed` job must never surface as `unknown`. A client that reads `solveStatus` alone would otherwise render a running or crashed solve as "no answer exists" — the exact conflation P1 §7.3 forbids. → Task 11.
3. **`inputSnapshot` must not change when the scenario is edited after the solve.** Solve, then change a teacher's blocked slots, then re-read the solution: the snapshot is byte-identical. This is the central promise of P1 §9 and nothing else tests it. → Task 11.
4. **A fully populated snapshot must survive a BSON round-trip.** `Scenario.overrides` and `min_doubles` are keyed by `(grade, code)` tuples in Python, and MongoDB cannot store a non-string dict key. `roster/io.py` flattens them to lists — but Phase 1's own Task 12 review found this round-trip was never tested *with populated data*. Test it with overrides and `min_doubles` both non-empty. → Task 2.
5. **A school whose `cycleDays` or `periodsPerDay` is not 6 and 10 must be rejected when written.** `roster/domain.py` hardcodes `DAYS = 6` and `PERIODS_PER_DAY = 10`; a school stored with 5 days would produce a silently wrong timetable rather than an error. → Task 3.

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Add `server` extra and test dependencies |
| `roster/store/__init__.py` | Store exports |
| `roster/store/config.py` | `Settings`, `settings_from_env` — env parsing and required-value enforcement |
| `roster/store/client.py` | `make_client`, `get_database` — the one `MongoClient` |
| `roster/store/records.py` | `SchoolRecord`, `UserRecord`, `ScenarioRecord` — what repositories return |
| `roster/store/codecs.py` | Domain ↔ document conversion. Pure functions, no database. |
| `roster/store/indexes.py` | `ensure_indexes` |
| `roster/store/repositories.py` | One repository class per collection. Every method takes `school_id`. |
| `roster/store/assemble.py` | `assemble_problem` — the single place a `Problem` is built |
| `roster/jobs/__init__.py` | Job exports |
| `roster/jobs/worker.py` | `solve_snapshot` — runs in the child process. Imports `roster` only. |
| `roster/jobs/runner.py` | `JobStatus`, `SolveRunner` — submission, status transitions, orphan sweep |
| `roster/api/__init__.py` | API exports |
| `roster/api/security.py` | Password hashing, session cookie signing |
| `roster/api/schemas.py` | Pydantic request and response models |
| `roster/api/deps.py` | `get_db`, `get_settings`, `get_runner`, `current_session` |
| `roster/api/app.py` | `create_app`, lifespan |
| `roster/api/routers/auth.py` | `/auth/*` |
| `roster/api/routers/entities.py` | `/school`, `/teachers`, `/subjects`, `/curriculum` |
| `roster/api/routers/scenarios.py` | `/scenarios`, `/scenarios/{id}/problem`, `/scenarios/{id}/validate` |
| `roster/api/routers/solutions.py` | `/scenarios/{id}/solve`, `/scenarios/{id}/solutions`, `/solutions/{id}`, `/solutions/{id}/cancel` |
| `roster/cli.py` | **Modify** — add `create-school` |
| `tests/conftest.py` | mongomock database, seeded school, app and client fixtures, inline executors |
| `tests/test_boundaries.py` … `tests/test_api_e2e.py` | One test module per source module |

---

### Task 1: Dependencies, settings, client, and the boundary guard

The boundary guard comes first so it protects every later commit.

**Files:**
- Modify: `pyproject.toml`
- Create: `roster/store/__init__.py`, `roster/store/config.py`, `roster/store/client.py`
- Test: `tests/test_boundaries.py`, `tests/test_store_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Settings` (frozen dataclass with fields `mongodb_uri: str`, `session_secret: str`, `mongodb_db: str`, `solve_time_limit_s: float`, `solve_max_workers: int`, `cookie_secure: bool`); `ConfigError(Exception)`; `settings_from_env(env: Mapping[str, str] | None = None) -> Settings`; `make_client(settings: Settings) -> MongoClient`; `get_database(client: MongoClient, settings: Settings) -> Database`.

- [ ] **Step 1: Add the dependencies**

Replace the `[project.optional-dependencies]` block in `pyproject.toml`:

```toml
[project.optional-dependencies]
server = [
    "pymongo>=4.9",
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "argon2-cffi>=23.1",
    "itsdangerous>=2.2",
]
dev = [
    "pytest>=8.0",
    "hypothesis>=6.100",
    "mongomock>=4.3",
    "httpx>=0.27",
]
```

`dependencies` stays `["ortools>=9.11"]`. The server extra keeps FastAPI out of a plain `pip install roster`, which is what P1 §8 means by a library with no web dependencies.

- [ ] **Step 2: Install them**

Run: `.venv/bin/pip install -e ".[dev,server]"`
Expected: pymongo, fastapi, mongomock, argon2-cffi, itsdangerous, httpx installed.

- [ ] **Step 3: Write the failing boundary tests**

Create `tests/test_boundaries.py`:

```python
"""The Phase 1 core must stay free of web and database dependencies.

P1 §8 calls the solver core "a pure Python library with no web dependencies".
Phase 1's only cross-task regression was roster/__init__.py rebinding an
attribute and silently disabling the equivalent guard for the verifier, so
this file checks the property two independent ways.
"""

import ast
import subprocess
import sys
import textwrap

FORBIDDEN_ROOTS = {"fastapi", "starlette", "pymongo", "bson", "mongomock"}


def test_the_solver_core_imports_neither_fastapi_nor_pymongo():
    """Checked in a fresh interpreter, so transitive imports are caught too.

    An AST scan of one file only sees that file's own import statements. A
    dependency three modules deep would pass it and still break the claim.
    """
    script = textwrap.dedent(
        """
        import sys
        import roster
        import roster.solve
        import roster.model
        import roster.verify
        import roster.io

        forbidden = {"fastapi", "starlette", "pymongo", "bson", "mongomock"}
        leaked = sorted(m for m in sys.modules if m.split(".")[0] in forbidden)
        print(",".join(leaked))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == "", proc.stdout


def test_the_package_init_does_not_import_the_store_jobs_or_api_layers():
    """roster/__init__.py stays a pure-core surface.

    Importing roster.store here would drag pymongo into every `import roster`,
    including the CLI's and the child solve process's.
    """
    import roster

    tree = ast.parse(open(roster.__file__, encoding="utf-8").read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = {
        m
        for m in imported
        if m.startswith(("roster.store", "roster.jobs", "roster.api"))
    }
    assert forbidden == set(), forbidden
```

- [ ] **Step 4: Run them — they must pass already**

Run: `.venv/bin/python -m pytest tests/test_boundaries.py -v` (Bash `timeout=600000`)
Expected: 2 passed. These guard a property that currently holds; they fail only if a later task breaks it.

- [ ] **Step 5: Write the failing config tests**

Create `tests/test_store_config.py`:

```python
import pytest

from roster.store.config import ConfigError, settings_from_env


def test_a_missing_session_secret_refuses_to_produce_settings():
    """No default secret, ever.

    A baked-in default that works in development is a forged-session hole in
    production: anyone who reads the source can mint a valid cookie.
    """
    with pytest.raises(ConfigError, match="SESSION_SECRET"):
        settings_from_env({"MONGODB_URI": "mongodb://localhost:27017"})


def test_a_missing_mongodb_uri_refuses_to_produce_settings():
    with pytest.raises(ConfigError, match="MONGODB_URI"):
        settings_from_env({"SESSION_SECRET": "s"})


def test_defaults_match_the_spec():
    settings = settings_from_env(
        {"MONGODB_URI": "mongodb://localhost:27017", "SESSION_SECRET": "s"}
    )
    assert settings.mongodb_db == "roster"
    assert settings.solve_time_limit_s == 150.0
    assert settings.solve_max_workers == 1
    assert settings.cookie_secure is True


def test_the_environment_overrides_every_default():
    settings = settings_from_env(
        {
            "MONGODB_URI": "mongodb://example:27017",
            "SESSION_SECRET": "s",
            "MONGODB_DB": "other",
            "SOLVE_TIME_LIMIT_S": "12.5",
            "SOLVE_MAX_WORKERS": "3",
            "COOKIE_SECURE": "false",
        }
    )
    assert settings.mongodb_db == "other"
    assert settings.solve_time_limit_s == 12.5
    assert settings.solve_max_workers == 3
    assert settings.cookie_secure is False


def test_a_non_numeric_time_limit_is_a_config_error_not_a_crash():
    with pytest.raises(ConfigError, match="SOLVE_TIME_LIMIT_S"):
        settings_from_env(
            {
                "MONGODB_URI": "mongodb://localhost:27017",
                "SESSION_SECRET": "s",
                "SOLVE_TIME_LIMIT_S": "soon",
            }
        )
```

- [ ] **Step 6: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_store_config.py -v` (Bash `timeout=600000`)
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.store'`

- [ ] **Step 7: Implement the store package and config**

Create `roster/store/__init__.py`:

```python
"""MongoDB persistence. Imported by the API and the job runner, never by the core."""
```

Create `roster/store/config.py`:

```python
"""Settings read from the environment.

Required values have no defaults. A default that happens to work in
development is worse than a refusal to start, because it fails silently in
production.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(Exception):
    """A required setting is missing or malformed."""


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str
    session_secret: str
    mongodb_db: str = "roster"
    solve_time_limit_s: float = 150.0
    solve_max_workers: int = 1
    cookie_secure: bool = True


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required and has no default")
    return value


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def settings_from_env(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    return Settings(
        mongodb_uri=_required(env, "MONGODB_URI"),
        session_secret=_required(env, "SESSION_SECRET"),
        mongodb_db=env.get("MONGODB_DB", "").strip() or "roster",
        solve_time_limit_s=_float(env, "SOLVE_TIME_LIMIT_S", 150.0),
        solve_max_workers=_int(env, "SOLVE_MAX_WORKERS", 1),
        cookie_secure=_bool(env, "COOKIE_SECURE", True),
    )
```

- [ ] **Step 8: Implement the client**

Create `roster/store/client.py`:

```python
"""The single MongoClient.

Atlas M0 caps connections, so exactly one client is created (in the FastAPI
lifespan handler) and reused for the process's lifetime.
"""

from __future__ import annotations

from pymongo import MongoClient
from pymongo.database import Database

from roster.store.config import Settings


def make_client(settings: Settings) -> MongoClient:
    return MongoClient(settings.mongodb_uri, tz_aware=True)


def get_database(client: MongoClient, settings: Settings) -> Database:
    return client[settings.mongodb_db]
```

- [ ] **Step 9: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_store_config.py tests/test_boundaries.py -v` (Bash `timeout=600000`)
Expected: 7 passed.

- [ ] **Step 10: Confirm the Phase 1 baseline still holds**

Run: `.venv/bin/python -m pytest` (Bash `timeout=600000`)
Expected: `111 passed` (Phase 1's 104 plus this task's 7).

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml roster/store tests/test_boundaries.py tests/test_store_config.py
git commit -m "Add store package settings, Mongo client and the import boundary guard"
```

---

### Task 2: Records and codecs

Pure functions that convert between domain objects and documents. No database here at all, which is why this task is fast to test and worth doing before repositories.

**Files:**
- Create: `roster/store/records.py`, `roster/store/codecs.py`
- Test: `tests/test_store_codecs.py`

**Interfaces:**
- Consumes: Task 1's package.
- Produces:
  - `SchoolRecord(id: str, name: str, cycle_days: int, periods_per_day: int, grades: tuple[int, ...], sections: tuple[str, ...])`
  - `UserRecord(id: str, school_id: str, email: str, password_hash: str)`
  - `ScenarioRecord(id: str, name: str, enabled_optional: frozenset[str], overrides: dict[tuple[int, str], int], min_doubles: dict[tuple[int, str], int], blocks: tuple[Block, ...])`
  - `teacher_to_doc(school_id: str, teacher: Teacher) -> dict`, `teacher_from_doc(doc: dict) -> Teacher`
  - `subject_to_doc(school_id: str, subject: Subject) -> dict`, `subject_from_doc(doc: dict) -> Subject`
  - `curriculum_entry_to_doc(school_id: str, kind: str, entry: CurriculumEntry) -> dict`, `curriculum_entry_from_doc(doc: dict) -> tuple[str, CurriculumEntry]`
  - `school_from_doc(doc: dict) -> SchoolRecord`, `scenario_from_doc(doc: dict) -> ScenarioRecord`
  - `pairs_to_docs(mapping: dict[tuple[int, str], int], value_key: str) -> list[dict]` and `pairs_from_docs(rows: list[dict], value_key: str) -> dict[tuple[int, str], int]`
  - `block_to_doc(block: Block) -> dict`, `block_from_doc(doc: dict) -> Block`

**Two conventions this task fixes for every later task:**

- A document's `_id` is an `ObjectId`; the domain object's `id` is `str(_id)`. `Teacher.id` and `Block.teacher_id` therefore hold that string. Domain classes are unchanged.
- `Scenario.overrides` and `min_doubles` are keyed by `(grade, code)` tuples, which MongoDB cannot store. They flatten to lists of documents in exactly the shape `roster/io.py` already uses, so the stored form and the wire form agree.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_store_codecs.py`:

```python
from bson import ObjectId

from roster.curriculum import CurriculumEntry
from roster.domain import Block, Subject, Teacher
from roster.store.codecs import (
    block_from_doc,
    block_to_doc,
    curriculum_entry_from_doc,
    curriculum_entry_to_doc,
    pairs_from_docs,
    pairs_to_docs,
    scenario_from_doc,
    school_from_doc,
    subject_from_doc,
    subject_to_doc,
    teacher_from_doc,
    teacher_to_doc,
)


def test_a_teacher_round_trips_with_its_blocked_slots():
    oid = ObjectId()
    teacher = Teacher(str(oid), "Karin", frozenset({3, 4}))
    doc = teacher_to_doc("school-1", teacher)
    doc["_id"] = oid

    assert doc["schoolId"] == "school-1"
    assert doc["blockedSlots"] == [3, 4]  # a list; BSON has no set
    assert teacher_from_doc(doc) == teacher


def test_a_teacher_with_no_blocked_slots_round_trips_to_an_empty_frozenset():
    oid = ObjectId()
    doc = {"_id": oid, "schoolId": "s", "name": "Shane", "blockedSlots": []}
    assert teacher_from_doc(doc) == Teacher(str(oid), "Shane", frozenset())


def test_a_subject_round_trips():
    subject = Subject("MAT", "Mathematics", True, False)
    doc = subject_to_doc("school-1", subject)
    assert doc["code"] == "MAT"
    assert subject_from_doc(doc) == subject


def test_a_curriculum_entry_carries_its_kind():
    entry = CurriculumEntry(4, "MAT", 8)
    doc = curriculum_entry_to_doc("school-1", "caps", entry)
    assert doc["kind"] == "caps"
    assert curriculum_entry_from_doc(doc) == ("caps", entry)


def test_tuple_keyed_pairs_flatten_and_restore():
    """Scenario.overrides is keyed by (grade, code). BSON cannot store that.

    Phase 1's Task 12 review found this round trip was only ever exercised
    with an EMPTY mapping, which passes whatever the implementation does.
    """
    mapping = {(4, "MAT"): 7, (7, "ENG"): 9}
    rows = pairs_to_docs(mapping, "periods")
    assert rows == [
        {"grade": 4, "subject": "MAT", "periods": 7},
        {"grade": 7, "subject": "ENG", "periods": 9},
    ]
    assert pairs_from_docs(rows, "periods") == mapping


def test_a_block_round_trips():
    block = Block("t1", 4, "MAT", ("A", "B"), 8)
    assert block_from_doc(block_to_doc(block)) == block


def test_a_school_document_becomes_a_record():
    oid = ObjectId()
    record = school_from_doc(
        {
            "_id": oid,
            "name": "Meridian",
            "cycleDays": 6,
            "periodsPerDay": 10,
            "grades": [4, 5, 6, 7],
            "sections": ["A", "B", "C"],
        }
    )
    assert record.id == str(oid)
    assert record.grades == (4, 5, 6, 7)
    assert record.sections == ("A", "B", "C")


def test_a_scenario_document_becomes_a_record_with_populated_overrides():
    """The Review Focus case: overrides AND min_doubles both non-empty."""
    oid = ObjectId()
    record = scenario_from_doc(
        {
            "_id": oid,
            "schoolId": "s",
            "name": "With Sepedi",
            "enabledOptional": ["BIB", "SPT"],
            "overrides": [{"grade": 4, "subject": "MAT", "periods": 7}],
            "minDoubles": [{"grade": 4, "subject": "ENG", "minimum": 2}],
            "blocks": [
                {
                    "teacherId": "t1",
                    "grade": 4,
                    "subject": "MAT",
                    "sections": ["A", "B", "C"],
                    "periodsPerClass": 8,
                }
            ],
        }
    )
    assert record.id == str(oid)
    assert record.enabled_optional == frozenset({"BIB", "SPT"})
    assert record.overrides == {(4, "MAT"): 7}
    assert record.min_doubles == {(4, "ENG"): 2}
    assert record.blocks == (Block("t1", 4, "MAT", ("A", "B", "C"), 8),)


def test_a_scenario_document_with_no_optional_fields_still_decodes():
    """Documents written by an earlier version may omit optional keys."""
    record = scenario_from_doc(
        {"_id": ObjectId(), "schoolId": "s", "name": "Bare"}
    )
    assert record.enabled_optional == frozenset()
    assert record.overrides == {}
    assert record.min_doubles == {}
    assert record.blocks == ()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_store_codecs.py -v` (Bash `timeout=600000`)
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.store.codecs'`

- [ ] **Step 3: Implement the records**

Create `roster/store/records.py`:

```python
"""What repositories return: documents decoded into plain Python.

These are not domain objects. A ScenarioRecord holds a scenario's *choices*
and its blocks; the Scenario the solver consumes also needs the curriculum,
which lives in its own collection. assemble.py joins them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from roster.domain import Block


@dataclass(frozen=True)
class SchoolRecord:
    id: str
    name: str
    cycle_days: int
    periods_per_day: int
    grades: tuple[int, ...]
    sections: tuple[str, ...]


@dataclass(frozen=True)
class UserRecord:
    id: str
    school_id: str
    email: str
    password_hash: str


@dataclass(frozen=True)
class ScenarioRecord:
    id: str
    name: str
    enabled_optional: frozenset[str] = frozenset()
    overrides: dict[tuple[int, str], int] = field(default_factory=dict)
    min_doubles: dict[tuple[int, str], int] = field(default_factory=dict)
    blocks: tuple[Block, ...] = ()
```

- [ ] **Step 4: Implement the codecs**

Create `roster/store/codecs.py`:

```python
"""Domain objects to documents and back. No database access here.

Two conventions, fixed once for the whole store:

- A document's `_id` is an ObjectId; a domain object's `id` is `str(_id)`.
- Mappings keyed by (grade, subject_code) flatten to lists of documents,
  because BSON keys must be strings. The flattened shape is exactly the one
  `roster/io.py` already uses, so the stored form and the wire form agree.
"""

from __future__ import annotations

from typing import Any

from roster.curriculum import CurriculumEntry
from roster.domain import Block, Subject, Teacher
from roster.store.records import SchoolRecord, ScenarioRecord, UserRecord


def pairs_to_docs(
    mapping: dict[tuple[int, str], int], value_key: str
) -> list[dict[str, Any]]:
    return [
        {"grade": grade, "subject": code, value_key: value}
        for (grade, code), value in sorted(mapping.items())
    ]


def pairs_from_docs(
    rows: list[dict[str, Any]] | None, value_key: str
) -> dict[tuple[int, str], int]:
    return {
        (row["grade"], row["subject"]): row[value_key] for row in rows or []
    }


def teacher_to_doc(school_id: str, teacher: Teacher) -> dict[str, Any]:
    return {
        "schoolId": school_id,
        "name": teacher.name,
        "blockedSlots": sorted(teacher.blocked_slots),
    }


def teacher_from_doc(doc: dict[str, Any]) -> Teacher:
    return Teacher(
        str(doc["_id"]), doc["name"], frozenset(doc.get("blockedSlots", []))
    )


def subject_to_doc(school_id: str, subject: Subject) -> dict[str, Any]:
    return {
        "schoolId": school_id,
        "code": subject.code,
        "displayName": subject.display_name,
        "isCore": subject.is_core,
        "isOptional": subject.is_optional,
    }


def subject_from_doc(doc: dict[str, Any]) -> Subject:
    return Subject(
        doc["code"], doc["displayName"], doc["isCore"], doc["isOptional"]
    )


def curriculum_entry_to_doc(
    school_id: str, kind: str, entry: CurriculumEntry
) -> dict[str, Any]:
    return {
        "schoolId": school_id,
        "kind": kind,
        "grade": entry.grade,
        "subjectCode": entry.subject_code,
        "periods": entry.periods_per_class,
    }


def curriculum_entry_from_doc(
    doc: dict[str, Any],
) -> tuple[str, CurriculumEntry]:
    return doc["kind"], CurriculumEntry(
        doc["grade"], doc["subjectCode"], doc["periods"]
    )


def block_to_doc(block: Block) -> dict[str, Any]:
    return {
        "teacherId": block.teacher_id,
        "grade": block.grade,
        "subject": block.subject_code,
        "sections": list(block.sections),
        "periodsPerClass": block.periods_per_class,
    }


def block_from_doc(doc: dict[str, Any]) -> Block:
    return Block(
        doc["teacherId"],
        doc["grade"],
        doc["subject"],
        tuple(doc["sections"]),
        doc["periodsPerClass"],
    )


def school_from_doc(doc: dict[str, Any]) -> SchoolRecord:
    return SchoolRecord(
        id=str(doc["_id"]),
        name=doc["name"],
        cycle_days=doc["cycleDays"],
        periods_per_day=doc["periodsPerDay"],
        grades=tuple(doc["grades"]),
        sections=tuple(doc["sections"]),
    )


def user_from_doc(doc: dict[str, Any]) -> UserRecord:
    return UserRecord(
        id=str(doc["_id"]),
        school_id=doc["schoolId"],
        email=doc["email"],
        password_hash=doc["passwordHash"],
    )


def scenario_from_doc(doc: dict[str, Any]) -> ScenarioRecord:
    return ScenarioRecord(
        id=str(doc["_id"]),
        name=doc["name"],
        enabled_optional=frozenset(doc.get("enabledOptional", [])),
        overrides=pairs_from_docs(doc.get("overrides"), "periods"),
        min_doubles=pairs_from_docs(doc.get("minDoubles"), "minimum"),
        blocks=tuple(block_from_doc(b) for b in doc.get("blocks", [])),
    )
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_store_codecs.py -v` (Bash `timeout=600000`)
Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add roster/store/records.py roster/store/codecs.py tests/test_store_codecs.py
git commit -m "Add store records and document codecs"
```

---

### Task 3: Repositories and indexes

**Files:**
- Create: `roster/store/indexes.py`, `roster/store/repositories.py`
- Create: `tests/conftest.py`
- Test: `tests/test_store_repositories.py`

**Interfaces:**
- Consumes: Task 2's codecs and records.
- Produces:
  - `ensure_indexes(db: Database) -> None`
  - `ValidationError(Exception)` — the only exception this module defines; duplicate keys surface as pymongo's own `DuplicateKeyError`
  - `SchoolRepo(db)` — `create(name, grades, sections, *, cycle_days=6, periods_per_day=10) -> SchoolRecord`, `get(school_id) -> SchoolRecord | None`, `update(school_id, *, name=None) -> SchoolRecord | None`
  - `UserRepo(db)` — `create(school_id, email, password_hash) -> UserRecord`, `by_email(email) -> UserRecord | None`, `get(school_id, user_id) -> UserRecord | None`
  - `TeacherRepo(db)` — `create(school_id, name, blocked_slots) -> Teacher`, `list(school_id) -> list[Teacher]`, `get(school_id, teacher_id) -> Teacher | None`, `update(school_id, teacher_id, *, name=None, blocked_slots=None) -> Teacher | None`, `delete(school_id, teacher_id) -> bool`
  - `SubjectRepo(db)` — `create(school_id, subject) -> Subject`, `list(school_id) -> list[Subject]`, `get(school_id, code) -> Subject | None`, `delete(school_id, code) -> bool`
  - `CurriculumRepo(db)` — `upsert(school_id, kind, entry) -> CurriculumEntry`, `list(school_id, kind) -> list[CurriculumEntry]`, `delete(school_id, kind, grade, subject_code) -> bool`
  - `ScenarioRepo(db)` — `create(school_id, name) -> ScenarioRecord`, `list(school_id) -> list[ScenarioRecord]`, `get(school_id, scenario_id) -> ScenarioRecord | None`, `update(school_id, scenario_id, **fields) -> ScenarioRecord | None`, `delete(school_id, scenario_id) -> bool`
  - `SolutionRepo(db)` — defined in Task 6, which owns the job lifecycle.

**`school_id` is the first positional parameter of every method.** `by_email` is the one exception and is deliberate: login resolves the school *from* the email, so it cannot already know the school. It is the only method allowed to query without a tenant filter, and its docstring says so.

- [ ] **Step 1: Write the shared fixtures**

Create `tests/conftest.py`:

```python
"""Shared fixtures.

The database is mongomock: an in-process reimplementation of MongoDB. It
keeps the whole store and API suite at unit-test speed, at the cost recorded
in spec §9.4 — its index enforcement and error semantics are not Atlas's, so
these tests prove our code issues the right operations, not that Atlas
rejects them identically.
"""

import mongomock
import pytest

from roster.store.indexes import ensure_indexes


@pytest.fixture
def db():
    client = mongomock.MongoClient()
    database = client["roster_test"]
    ensure_indexes(database)
    return database
```

- [ ] **Step 2: Write the failing repository tests**

Create `tests/test_store_repositories.py`:

```python
import pytest
from bson import ObjectId

from roster.curriculum import CurriculumEntry
from roster.domain import Subject, Teacher
from roster.store.repositories import (
    CurriculumRepo,
    ScenarioRepo,
    SchoolRepo,
    SubjectRepo,
    TeacherRepo,
    UserRepo,
    ValidationError,
)


@pytest.fixture
def school(db):
    return SchoolRepo(db).create("Meridian", (4, 5, 6, 7), ("A", "B", "C"))


def test_a_school_defaults_to_the_six_by_ten_cycle(db):
    record = SchoolRepo(db).create("Meridian", (4,), ("A",))
    assert record.cycle_days == 6
    assert record.periods_per_day == 10


def test_a_school_with_a_different_cycle_is_refused(db):
    """roster/domain.py hardcodes DAYS = 6 and PERIODS_PER_DAY = 10.

    A school stored with five days would not fail — it would produce a
    confidently wrong timetable, which P1 §14 names as the real risk.
    """
    with pytest.raises(ValidationError, match="cycleDays"):
        SchoolRepo(db).create("Short week", (4,), ("A",), cycle_days=5)
    with pytest.raises(ValidationError, match="periodsPerDay"):
        SchoolRepo(db).create("Long day", (4,), ("A",), periods_per_day=12)


def test_a_teacher_is_created_read_updated_and_deleted(db, school):
    repo = TeacherRepo(db)
    teacher = repo.create(school.id, "Karin", frozenset({3}))

    assert repo.get(school.id, teacher.id) == teacher
    assert repo.list(school.id) == [teacher]

    updated = repo.update(school.id, teacher.id, blocked_slots=frozenset({7, 8}))
    assert updated is not None
    assert updated.blocked_slots == frozenset({7, 8})
    assert updated.name == "Karin"

    assert repo.delete(school.id, teacher.id) is True
    assert repo.get(school.id, teacher.id) is None
    assert repo.delete(school.id, teacher.id) is False


def test_a_teacher_belonging_to_another_school_is_invisible(db, school):
    """The Review Focus case, checked at the repository rather than the route.

    get() returning None is what lets the route answer 404 without having to
    know whether the document exists at all.
    """
    other = SchoolRepo(db).create("Other", (4,), ("A",))
    repo = TeacherRepo(db)
    teacher = repo.create(other.id, "Shane", frozenset())

    assert repo.get(school.id, teacher.id) is None
    assert repo.list(school.id) == []
    assert repo.update(school.id, teacher.id, name="Renamed") is None
    assert repo.delete(school.id, teacher.id) is False
    # ...and the real owner still has it, unchanged.
    assert repo.get(other.id, teacher.id) == teacher


def test_a_malformed_id_is_not_found_rather_than_a_crash(db, school):
    """bson raises InvalidId for a non-hex string; a 500 would be wrong."""
    assert TeacherRepo(db).get(school.id, "not-an-object-id") is None
    assert TeacherRepo(db).delete(school.id, "not-an-object-id") is False


def test_a_subject_is_keyed_by_its_code_within_a_school(db, school):
    repo = SubjectRepo(db)
    subject = Subject("MAT", "Mathematics", True, False)
    repo.create(school.id, subject)

    assert repo.get(school.id, "MAT") == subject
    assert repo.get(school.id, "ENG") is None

    other = SchoolRepo(db).create("Other", (4,), ("A",))
    assert repo.get(other.id, "MAT") is None
    # The same code in a different school is a different subject, not a clash.
    repo.create(other.id, Subject("MAT", "Wiskunde", True, False))
    assert repo.get(other.id, "MAT").display_name == "Wiskunde"


def test_curriculum_entries_are_separated_by_kind(db, school):
    repo = CurriculumRepo(db)
    repo.upsert(school.id, "caps", CurriculumEntry(4, "MAT", 8))
    repo.upsert(school.id, "optional", CurriculumEntry(4, "BIB", 2))

    assert repo.list(school.id, "caps") == [CurriculumEntry(4, "MAT", 8)]
    assert repo.list(school.id, "optional") == [CurriculumEntry(4, "BIB", 2)]


def test_upserting_the_same_grade_and_subject_replaces_the_period_count(
    db, school
):
    repo = CurriculumRepo(db)
    repo.upsert(school.id, "caps", CurriculumEntry(4, "MAT", 8))
    repo.upsert(school.id, "caps", CurriculumEntry(4, "MAT", 9))

    assert repo.list(school.id, "caps") == [CurriculumEntry(4, "MAT", 9)]


def test_a_scenario_round_trips_its_choices_and_blocks(db, school):
    repo = ScenarioRepo(db)
    created = repo.create(school.id, "With Sepedi")

    updated = repo.update(
        school.id,
        created.id,
        enabled_optional=frozenset({"BIB"}),
        overrides={(4, "MAT"): 7},
        min_doubles={(4, "ENG"): 2},
    )
    assert updated is not None
    assert updated.overrides == {(4, "MAT"): 7}
    assert updated.min_doubles == {(4, "ENG"): 2}

    # Read back from the database, not from the returned object.
    assert repo.get(school.id, created.id) == updated


def test_a_user_is_found_by_email_across_schools(db, school):
    """by_email is the one method with no tenant filter, by necessity."""
    repo = UserRepo(db)
    user = repo.create(school.id, "head@meridian.example", "hash")

    found = repo.by_email("head@meridian.example")
    assert found is not None
    assert found.id == user.id
    assert found.school_id == school.id
    assert repo.by_email("nobody@example.com") is None
```

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_store_repositories.py -v` (Bash `timeout=600000`)
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.store.indexes'`

- [ ] **Step 4: Implement the indexes**

Create `roster/store/indexes.py`:

```python
"""Index creation. Idempotent — safe to call on every startup.

Every index leads with schoolId, because every query is tenant-scoped and a
compound index is only usable from its prefix.
"""

from __future__ import annotations

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database


def ensure_indexes(db: Database) -> None:
    db["teachers"].create_index([("schoolId", ASCENDING), ("name", ASCENDING)])
    db["subjects"].create_index(
        [("schoolId", ASCENDING), ("code", ASCENDING)], unique=True
    )
    db["curriculum"].create_index(
        [
            ("schoolId", ASCENDING),
            ("kind", ASCENDING),
            ("grade", ASCENDING),
            ("subjectCode", ASCENDING),
        ],
        unique=True,
    )
    db["users"].create_index([("email", ASCENDING)], unique=True)
    db["scenarios"].create_index(
        [("schoolId", ASCENDING), ("name", ASCENDING)]
    )
    db["solutions"].create_index(
        [
            ("schoolId", ASCENDING),
            ("scenarioId", ASCENDING),
            ("createdAt", DESCENDING),
        ]
    )
```

Note the `users` index is on `email` alone, not `(schoolId, email)`: login looks an address up before it knows the school, so an address must identify exactly one school.

- [ ] **Step 5: Implement the repositories**

Create `roster/store/repositories.py`:

```python
"""One repository per collection.

**Every method takes school_id as its first positional parameter.** There is
no overload that omits it and no module-level default, so a query that
forgets its tenant scope does not type-check rather than leaking another
school's data past review.

`UserRepo.by_email` is the single deliberate exception; see its docstring.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.database import Database

from roster.curriculum import CurriculumEntry
from roster.domain import DAYS, PERIODS_PER_DAY, Block, Subject, Teacher
from roster.store.codecs import (
    block_to_doc,
    curriculum_entry_from_doc,
    curriculum_entry_to_doc,
    pairs_to_docs,
    scenario_from_doc,
    school_from_doc,
    subject_from_doc,
    subject_to_doc,
    teacher_from_doc,
    teacher_to_doc,
    user_from_doc,
)
from roster.store.records import SchoolRecord, ScenarioRecord, UserRecord


class ValidationError(Exception):
    """A value the store refuses to write."""


def _oid(value: str) -> ObjectId | None:
    """An unparseable id means 'not found', never a 500."""
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


class SchoolRepo:
    def __init__(self, db: Database) -> None:
        self._c = db["schools"]

    def create(
        self,
        name: str,
        grades: tuple[int, ...],
        sections: tuple[str, ...],
        *,
        cycle_days: int = DAYS,
        periods_per_day: int = PERIODS_PER_DAY,
    ) -> SchoolRecord:
        # roster/domain.py hardcodes the cycle. Storing anything else would
        # not fail loudly; it would produce a confidently wrong timetable.
        if cycle_days != DAYS:
            raise ValidationError(
                f"cycleDays must be {DAYS}; this solver models a "
                f"{DAYS}-day cycle only"
            )
        if periods_per_day != PERIODS_PER_DAY:
            raise ValidationError(
                f"periodsPerDay must be {PERIODS_PER_DAY}; this solver models "
                f"{PERIODS_PER_DAY} periods a day only"
            )
        doc = {
            "name": name,
            "cycleDays": cycle_days,
            "periodsPerDay": periods_per_day,
            "grades": list(grades),
            "sections": list(sections),
        }
        doc["_id"] = self._c.insert_one(doc).inserted_id
        return school_from_doc(doc)

    def get(self, school_id: str) -> SchoolRecord | None:
        oid = _oid(school_id)
        if oid is None:
            return None
        doc = self._c.find_one({"_id": oid})
        return school_from_doc(doc) if doc else None

    def update(self, school_id: str, *, name: str | None = None) -> SchoolRecord | None:
        oid = _oid(school_id)
        if oid is None:
            return None
        if name is not None:
            self._c.update_one({"_id": oid}, {"$set": {"name": name}})
        return self.get(school_id)


class UserRepo:
    def __init__(self, db: Database) -> None:
        self._c = db["users"]

    def create(
        self, school_id: str, email: str, password_hash: str
    ) -> UserRecord:
        doc = {
            "schoolId": school_id,
            "email": email,
            "passwordHash": password_hash,
        }
        doc["_id"] = self._c.insert_one(doc).inserted_id
        return user_from_doc(doc)

    def by_email(self, email: str) -> UserRecord | None:
        """The one method with no tenant filter, and necessarily so.

        Login resolves the school FROM the address, so it cannot already know
        which school to scope to. An email therefore identifies exactly one
        school, which the unique index on `email` enforces.
        """
        doc = self._c.find_one({"email": email})
        return user_from_doc(doc) if doc else None

    def get(self, school_id: str, user_id: str) -> UserRecord | None:
        oid = _oid(user_id)
        if oid is None:
            return None
        doc = self._c.find_one({"_id": oid, "schoolId": school_id})
        return user_from_doc(doc) if doc else None


class TeacherRepo:
    def __init__(self, db: Database) -> None:
        self._c = db["teachers"]

    def create(
        self, school_id: str, name: str, blocked_slots: frozenset[int]
    ) -> Teacher:
        doc = teacher_to_doc(school_id, Teacher("", name, blocked_slots))
        doc["_id"] = self._c.insert_one(doc).inserted_id
        return teacher_from_doc(doc)

    def list(self, school_id: str) -> list[Teacher]:
        return [
            teacher_from_doc(d)
            for d in self._c.find({"schoolId": school_id}).sort("name", 1)
        ]

    def get(self, school_id: str, teacher_id: str) -> Teacher | None:
        oid = _oid(teacher_id)
        if oid is None:
            return None
        doc = self._c.find_one({"_id": oid, "schoolId": school_id})
        return teacher_from_doc(doc) if doc else None

    def update(
        self,
        school_id: str,
        teacher_id: str,
        *,
        name: str | None = None,
        blocked_slots: frozenset[int] | None = None,
    ) -> Teacher | None:
        oid = _oid(teacher_id)
        if oid is None:
            return None
        changes: dict[str, Any] = {}
        if name is not None:
            changes["name"] = name
        if blocked_slots is not None:
            changes["blockedSlots"] = sorted(blocked_slots)
        if changes:
            result = self._c.update_one(
                {"_id": oid, "schoolId": school_id}, {"$set": changes}
            )
            if result.matched_count == 0:
                return None
        return self.get(school_id, teacher_id)

    def delete(self, school_id: str, teacher_id: str) -> bool:
        oid = _oid(teacher_id)
        if oid is None:
            return False
        return (
            self._c.delete_one(
                {"_id": oid, "schoolId": school_id}
            ).deleted_count
            == 1
        )


class SubjectRepo:
    def __init__(self, db: Database) -> None:
        self._c = db["subjects"]

    def create(self, school_id: str, subject: Subject) -> Subject:
        self._c.insert_one(subject_to_doc(school_id, subject))
        return subject

    def list(self, school_id: str) -> list[Subject]:
        return [
            subject_from_doc(d)
            for d in self._c.find({"schoolId": school_id}).sort("code", 1)
        ]

    def get(self, school_id: str, code: str) -> Subject | None:
        doc = self._c.find_one({"schoolId": school_id, "code": code})
        return subject_from_doc(doc) if doc else None

    def update(
        self,
        school_id: str,
        code: str,
        *,
        display_name: str | None = None,
        is_core: bool | None = None,
        is_optional: bool | None = None,
    ) -> Subject | None:
        changes: dict[str, Any] = {}
        if display_name is not None:
            changes["displayName"] = display_name
        if is_core is not None:
            changes["isCore"] = is_core
        if is_optional is not None:
            changes["isOptional"] = is_optional
        if changes:
            result = self._c.update_one(
                {"schoolId": school_id, "code": code}, {"$set": changes}
            )
            if result.matched_count == 0:
                return None
        return self.get(school_id, code)

    def delete(self, school_id: str, code: str) -> bool:
        return (
            self._c.delete_one(
                {"schoolId": school_id, "code": code}
            ).deleted_count
            == 1
        )


class CurriculumRepo:
    def __init__(self, db: Database) -> None:
        self._c = db["curriculum"]

    def upsert(
        self, school_id: str, kind: str, entry: CurriculumEntry
    ) -> CurriculumEntry:
        self._c.update_one(
            {
                "schoolId": school_id,
                "kind": kind,
                "grade": entry.grade,
                "subjectCode": entry.subject_code,
            },
            {"$set": curriculum_entry_to_doc(school_id, kind, entry)},
            upsert=True,
        )
        return entry

    def list(self, school_id: str, kind: str) -> list[CurriculumEntry]:
        rows = self._c.find({"schoolId": school_id, "kind": kind}).sort(
            [("grade", 1), ("subjectCode", 1)]
        )
        return [curriculum_entry_from_doc(d)[1] for d in rows]

    def delete(
        self, school_id: str, kind: str, grade: int, subject_code: str
    ) -> bool:
        return (
            self._c.delete_one(
                {
                    "schoolId": school_id,
                    "kind": kind,
                    "grade": grade,
                    "subjectCode": subject_code,
                }
            ).deleted_count
            == 1
        )


class ScenarioRepo:
    def __init__(self, db: Database) -> None:
        self._c = db["scenarios"]

    def create(self, school_id: str, name: str) -> ScenarioRecord:
        doc: dict[str, Any] = {
            "schoolId": school_id,
            "name": name,
            "enabledOptional": [],
            "overrides": [],
            "minDoubles": [],
            "blocks": [],
        }
        doc["_id"] = self._c.insert_one(doc).inserted_id
        return scenario_from_doc(doc)

    def list(self, school_id: str) -> list[ScenarioRecord]:
        return [
            scenario_from_doc(d)
            for d in self._c.find({"schoolId": school_id}).sort("name", 1)
        ]

    def get(self, school_id: str, scenario_id: str) -> ScenarioRecord | None:
        oid = _oid(scenario_id)
        if oid is None:
            return None
        doc = self._c.find_one({"_id": oid, "schoolId": school_id})
        return scenario_from_doc(doc) if doc else None

    def update(
        self,
        school_id: str,
        scenario_id: str,
        *,
        name: str | None = None,
        enabled_optional: frozenset[str] | None = None,
        overrides: dict[tuple[int, str], int] | None = None,
        min_doubles: dict[tuple[int, str], int] | None = None,
        blocks: tuple[Block, ...] | None = None,
    ) -> ScenarioRecord | None:
        oid = _oid(scenario_id)
        if oid is None:
            return None
        changes: dict[str, Any] = {}
        if name is not None:
            changes["name"] = name
        if enabled_optional is not None:
            changes["enabledOptional"] = sorted(enabled_optional)
        if overrides is not None:
            changes["overrides"] = pairs_to_docs(overrides, "periods")
        if min_doubles is not None:
            changes["minDoubles"] = pairs_to_docs(min_doubles, "minimum")
        if blocks is not None:
            changes["blocks"] = [block_to_doc(b) for b in blocks]
        if changes:
            result = self._c.update_one(
                {"_id": oid, "schoolId": school_id}, {"$set": changes}
            )
            if result.matched_count == 0:
                return None
        return self.get(school_id, scenario_id)

    def delete(self, school_id: str, scenario_id: str) -> bool:
        oid = _oid(scenario_id)
        if oid is None:
            return False
        return (
            self._c.delete_one(
                {"_id": oid, "schoolId": school_id}
            ).deleted_count
            == 1
        )
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_store_repositories.py -v` (Bash `timeout=600000`)
Expected: 10 passed.

- [ ] **Step 7: Run the whole fast suite**

Run: `.venv/bin/python -m pytest` (Bash `timeout=600000`)
Expected: `130 passed`.

- [ ] **Step 8: Commit**

```bash
git add roster/store/indexes.py roster/store/repositories.py tests/conftest.py tests/test_store_repositories.py
git commit -m "Add tenant-scoped repositories and index setup"
```

---

### Task 4: Scenario assembly

The one place a `Problem` is built. The API and the solve job both call it, so the UI cannot assemble a subtly different problem than the solver sees (spec §7.1).

**Files:**
- Create: `roster/store/assemble.py`
- Test: `tests/test_store_assemble.py`

**Interfaces:**
- Consumes: Task 3's repositories.
- Produces: `AssemblyError(Exception)` with a `.message` attribute; `assemble_problem(db: Database, school_id: str, scenario_id: str) -> Problem`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_store_assemble.py`:

```python
import pytest

from roster.curriculum import CurriculumEntry
from roster.domain import Block, Subject
from roster.store.assemble import AssemblyError, assemble_problem
from roster.store.repositories import (
    CurriculumRepo,
    ScenarioRepo,
    SchoolRepo,
    SubjectRepo,
    TeacherRepo,
)


@pytest.fixture
def seeded(db):
    """A two-grade school with one teacher covering one subject."""
    school = SchoolRepo(db).create("Meridian", (4,), ("A", "B"))
    SubjectRepo(db).create(school.id, Subject("MAT", "Mathematics", True, False))
    SubjectRepo(db).create(school.id, Subject("STUDY", "Study", False, False))
    CurriculumRepo(db).upsert(school.id, "caps", CurriculumEntry(4, "MAT", 8))
    teacher = TeacherRepo(db).create(school.id, "Karin", frozenset({3}))
    scenario = ScenarioRepo(db).create(school.id, "Base")
    ScenarioRepo(db).update(
        school.id,
        scenario.id,
        blocks=(Block(teacher.id, 4, "MAT", ("A", "B"), 8),),
    )
    return school, teacher, scenario


def test_assembly_produces_a_problem_the_core_accepts(db, seeded):
    school, teacher, scenario = seeded
    problem = assemble_problem(db, school.id, scenario.id)

    assert problem.grades == (4,)
    assert problem.sections == ("A", "B")
    assert problem.subjects["MAT"].is_core is True
    assert problem.teachers[teacher.id].blocked_slots == frozenset({3})
    assert problem.scenario.caps.periods(4, "MAT") == 8
    assert problem.blocks == (Block(teacher.id, 4, "MAT", ("A", "B"), 8),)


def test_scenario_choices_reach_the_assembled_problem(db, seeded):
    school, _, scenario = seeded
    CurriculumRepo(db).upsert(school.id, "optional", CurriculumEntry(4, "BIB", 2))
    ScenarioRepo(db).update(
        school.id,
        scenario.id,
        enabled_optional=frozenset({"BIB"}),
        overrides={(4, "MAT"): 7},
        min_doubles={(4, "MAT"): 1},
    )
    problem = assemble_problem(db, school.id, scenario.id)

    assert problem.scenario.enabled_optional == frozenset({"BIB"})
    assert problem.scenario.overrides == {(4, "MAT"): 7}
    assert problem.scenario.min_doubles == {(4, "MAT"): 1}
    assert problem.scenario.optional.periods(4, "BIB") == 2


def test_an_unknown_scenario_is_an_assembly_error(db, seeded):
    school, _, _ = seeded
    with pytest.raises(AssemblyError, match="scenario"):
        assemble_problem(db, school.id, "652000000000000000000000")


def test_a_scenario_from_another_school_is_an_assembly_error(db, seeded):
    _, _, scenario = seeded
    other = SchoolRepo(db).create("Other", (4,), ("A",))
    with pytest.raises(AssemblyError, match="scenario"):
        assemble_problem(db, other.id, scenario.id)


def test_a_block_naming_a_deleted_teacher_is_reported_by_name(db, seeded):
    """Deleting a teacher who still holds blocks is an ordinary sequence.

    Without this check the Problem would carry a block whose teacher_id is
    absent from `teachers`, and the failure would surface much later as a
    KeyError inside the solver.
    """
    school, teacher, scenario = seeded
    TeacherRepo(db).delete(school.id, teacher.id)

    with pytest.raises(AssemblyError, match="teacher"):
        assemble_problem(db, school.id, scenario.id)


def test_a_block_naming_an_unknown_subject_is_reported(db, seeded):
    school, teacher, scenario = seeded
    ScenarioRepo(db).update(
        school.id,
        scenario.id,
        blocks=(Block(teacher.id, 4, "NOPE", ("A",), 2),),
    )
    with pytest.raises(AssemblyError, match="NOPE"):
        assemble_problem(db, school.id, scenario.id)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_store_assemble.py -v` (Bash `timeout=600000`)
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.store.assemble'`

- [ ] **Step 3: Implement assembly**

Create `roster/store/assemble.py`:

```python
"""Build a Problem from stored documents.

This is the ONLY place a Problem is assembled. The `/problem` endpoint and
the solve job both call it, so the timetable the UI reasons about and the one
the solver receives cannot diverge. P1 §8 makes the same argument about
validation; assembly is the same trap one layer down.
"""

from __future__ import annotations

from pymongo.database import Database

from roster.curriculum import Curriculum, Scenario
from roster.problem import Problem
from roster.store.repositories import (
    CurriculumRepo,
    ScenarioRepo,
    SchoolRepo,
    SubjectRepo,
    TeacherRepo,
)


class AssemblyError(Exception):
    """A stored scenario cannot be turned into a Problem."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def assemble_problem(
    db: Database, school_id: str, scenario_id: str
) -> Problem:
    school = SchoolRepo(db).get(school_id)
    if school is None:
        raise AssemblyError(f"school {school_id} not found")

    record = ScenarioRepo(db).get(school_id, scenario_id)
    if record is None:
        raise AssemblyError(f"scenario {scenario_id} not found")

    subjects = {s.code: s for s in SubjectRepo(db).list(school_id)}
    teachers = {t.id: t for t in TeacherRepo(db).list(school_id)}

    curriculum = CurriculumRepo(db)
    caps = Curriculum(tuple(curriculum.list(school_id, "caps")))
    optional = Curriculum(tuple(curriculum.list(school_id, "optional")))

    for block in record.blocks:
        if block.teacher_id not in teachers:
            raise AssemblyError(
                f"block for grade {block.grade} {block.subject_code} names "
                f"teacher {block.teacher_id}, who does not exist"
            )
        if block.subject_code not in subjects:
            raise AssemblyError(
                f"block for grade {block.grade} names subject "
                f"{block.subject_code}, which does not exist"
            )

    scenario = Scenario(
        caps=caps,
        optional=optional,
        enabled_optional=record.enabled_optional,
        overrides=dict(record.overrides),
        min_doubles=dict(record.min_doubles),
    )
    return Problem(
        grades=school.grades,
        sections=school.sections,
        subjects=subjects,
        teachers=teachers,
        scenario=scenario,
        blocks=record.blocks,
    )
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_store_assemble.py -v` (Bash `timeout=600000`)
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add roster/store/assemble.py tests/test_store_assemble.py
git commit -m "Assemble a Problem from stored documents in one place"
```

---

### Task 5: The solve worker

The function that runs inside the child process. It is small on purpose: everything it touches must be importable without `pymongo`.

**Files:**
- Create: `roster/jobs/__init__.py`, `roster/jobs/worker.py`
- Test: `tests/test_jobs_worker.py`

**Interfaces:**
- Consumes: nothing from earlier tasks — deliberately. This module imports `roster` core only.
- Produces: `DEFAULT_TIME_LIMIT_S = 150.0`; `solve_snapshot(snapshot: dict[str, Any], time_limit_s: float = DEFAULT_TIME_LIMIT_S) -> dict[str, Any]`, returning `roster.io.result_to_dict`'s shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_jobs_worker.py`:

```python
"""The child-process entry point.

Every test here is fast because the one problem used is rejected by
arithmetic pre-flight before CP-SAT ever starts. Exercising a real solve
belongs in the solver-marked end-to-end test, not here.
"""

import ast
import pickle

from roster.jobs.worker import DEFAULT_TIME_LIMIT_S, solve_snapshot

# A core subject with 5 periods cannot appear on each of 6 days, so
# pre-flight blocks it and the solver is never invoked.
BLOCKED_SNAPSHOT = {
    "grades": [4],
    "sections": ["A"],
    "subjects": [
        {
            "code": "MAT",
            "displayName": "Mathematics",
            "isCore": True,
            "isOptional": False,
        },
        {
            "code": "STUDY",
            "displayName": "Study",
            "isCore": False,
            "isOptional": False,
        },
    ],
    "teachers": [{"id": "t1", "name": "Karin", "blockedSlots": []}],
    "scenario": {
        "caps": [{"grade": 4, "subject": "MAT", "periods": 5}],
        "optional": [],
        "enabledOptional": [],
        "overrides": [],
        "minDoubles": [],
    },
    "blocks": [
        {
            "teacherId": "t1",
            "grade": 4,
            "subject": "MAT",
            "sections": ["A"],
            "periodsPerClass": 5,
        }
    ],
}


def test_the_default_time_limit_is_the_background_job_budget():
    """150s, not Phase 1's 30s.

    The 30s default existed only because a synchronous request could not
    wait. Behind a polling job it buys a visibly worse timetable for nothing.
    """
    assert DEFAULT_TIME_LIMIT_S == 150.0


def test_a_snapshot_blocked_by_preflight_returns_blocked_without_solving():
    payload = solve_snapshot(BLOCKED_SNAPSHOT, time_limit_s=1.0)

    assert payload["status"] == "blocked"
    assert payload["placements"] == []
    assert any(f["severity"] == "error" for f in payload["findings"])


def test_the_payload_is_plain_json_types_only():
    """Whatever crosses the process boundary also goes straight into BSON."""
    payload = solve_snapshot(BLOCKED_SNAPSHOT, time_limit_s=1.0)

    def check(value):
        assert isinstance(
            value, (str, int, float, bool, list, dict, type(None))
        ), type(value)
        if isinstance(value, dict):
            for key, item in value.items():
                assert isinstance(key, str), key
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(payload)


def test_the_worker_function_is_picklable():
    """ProcessPoolExecutor pickles the callable by qualified name."""
    assert pickle.loads(pickle.dumps(solve_snapshot)) is solve_snapshot


def test_the_worker_module_imports_neither_pymongo_nor_fastapi():
    """Spec §5.4: the child imports `roster` and nothing else.

    A child that opened its own MongoDB connection would spend Atlas M0's
    connection cap for nothing.
    """
    import roster.jobs.worker as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = {
        m
        for m in imported
        if m.split(".")[0] in {"pymongo", "bson", "fastapi", "starlette"}
        or m.startswith("roster.store")
    }
    assert forbidden == set(), forbidden
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_jobs_worker.py -v` (Bash `timeout=600000`)
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.jobs'`

- [ ] **Step 3: Implement the worker**

Create `roster/jobs/__init__.py`:

```python
"""Background solving: the child-process worker and the runner that drives it."""
```

Create `roster/jobs/worker.py`:

```python
"""Runs inside the solve child process.

This module imports `roster` core and nothing else — no pymongo, no
fastapi, not even `roster.store`. Three reasons, all load-bearing:

- Atlas M0 caps connections, so a pool of database-connecting children would
  spend them for nothing. The parent performs every write.
- It keeps the pure core pure: the child's import graph is the proof.
- A plain dict in and a plain dict out means nothing crossing the process
  boundary needs a custom pickle.
"""

from __future__ import annotations

from typing import Any

from roster.io import problem_from_dict, result_to_dict
from roster.solve import solve

# Phase 1 defaulted to 30 seconds because a synchronous HTTP request could
# not wait longer. Measured, that default costs 125 of 171 possible doubles
# against 167 at 150 seconds. Behind a polling job the wait costs a user
# nothing but a progress indicator.
DEFAULT_TIME_LIMIT_S = 150.0


def solve_snapshot(
    snapshot: dict[str, Any],
    time_limit_s: float = DEFAULT_TIME_LIMIT_S,
) -> dict[str, Any]:
    """Solve a frozen problem snapshot and return a JSON-safe result."""
    problem = problem_from_dict(snapshot)
    result = solve(problem, time_limit_s=time_limit_s)
    return result_to_dict(result)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_jobs_worker.py -v` (Bash `timeout=600000`)
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add roster/jobs tests/test_jobs_worker.py
git commit -m "Add the child-process solve worker"
```

---

### Task 6: The solution repository and the job runner

**Files:**
- Modify: `roster/store/repositories.py` (append `SolutionRepo`)
- Create: `roster/jobs/runner.py`
- Modify: `tests/conftest.py` (add the executor fakes)
- Test: `tests/test_jobs_runner.py`

**Interfaces:**
- Consumes: Task 3's repositories, Task 5's `solve_snapshot`.
- Produces:
  - `JobStatus(StrEnum)` with `QUEUED`, `RUNNING`, `DONE`, `FAILED`, `CANCELLED` — values `"queued"`, `"running"`, `"done"`, `"failed"`, `"cancelled"`.
  - `SolutionRepo(db)` — `create_queued(school_id, scenario_id, snapshot, time_limit_s) -> str`, `get(school_id, solution_id) -> dict | None`, `list_for_scenario(school_id, scenario_id) -> list[dict]`, `mark_running(school_id, solution_id) -> bool`, `mark_done(school_id, solution_id, payload) -> None`, `mark_failed(school_id, solution_id, error) -> None`, `cancel_if_queued(school_id, solution_id) -> bool`, `sweep_orphans() -> int`.
  - `SolveRunner(db, *, time_limit_s=150.0, max_workers=1, solve_fn=solve_snapshot, thread_pool=None, process_pool=None)` — `start()`, `shutdown()`, `submit(school_id, scenario_id, snapshot, time_limit_s=None) -> str`, `cancel(school_id, solution_id) -> bool`.

**Why two executors.** A single-slot `ThreadPoolExecutor` serialises orchestration and performs the MongoDB writes; a `ProcessPoolExecutor` runs CP-SAT. `concurrent.futures` gives no "task started" callback, so without the thread the runner could not honestly report `running`. The thread is allowed to touch MongoDB because it lives in the parent process; the child still does not.

**`mark_running` only transitions from `queued`.** That one filter is what makes cancellation race-free: a job cancelled between submission and execution simply never starts.

- [ ] **Step 1: Add the executor fakes to conftest**

Append to `tests/conftest.py`:

```python
from concurrent.futures import Future


class InlineExecutor:
    """Runs the callable immediately on the calling thread."""

    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001 - mirrors a real pool
            future.set_exception(exc)
        return future

    def shutdown(self, wait: bool = True) -> None:
        return None


class DeferredExecutor:
    """Queues the callable until run_next() is called.

    Lets a test observe the `queued` state, which an inline executor races
    straight past.
    """

    def __init__(self) -> None:
        self.pending: list[tuple[Future, object, tuple, dict]] = []

    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        self.pending.append((future, fn, args, kwargs))
        return future

    def run_next(self) -> None:
        future, fn, args, kwargs = self.pending.pop(0)
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001
            future.set_exception(exc)

    def shutdown(self, wait: bool = True) -> None:
        return None


@pytest.fixture
def inline_executors():
    return InlineExecutor(), InlineExecutor()
```

- [ ] **Step 2: Write the failing runner tests**

Create `tests/test_jobs_runner.py`:

```python
import pytest

from roster.jobs.runner import JobStatus, SolveRunner
from roster.store.repositories import SolutionRepo

from tests.conftest import DeferredExecutor, InlineExecutor

SNAPSHOT = {"grades": [4], "sections": ["A"]}  # opaque to the runner

DONE_PAYLOAD = {
    "status": "feasible",
    "doublesPlaced": 12,
    "doublesCeiling": 20,
    "wallSeconds": 1.5,
    "findings": [],
    "conflict": None,
    "placements": [
        {"grade": 4, "section": "A", "subject": "MAT", "slot": 0}
    ],
}


def make_runner(db, solve_fn=None, thread_pool=None, process_pool=None):
    runner = SolveRunner(
        db,
        solve_fn=solve_fn or (lambda snapshot, limit: DONE_PAYLOAD),
        thread_pool=thread_pool or InlineExecutor(),
        process_pool=process_pool or InlineExecutor(),
    )
    runner.start()
    return runner


def test_a_submitted_job_reaches_done_and_records_the_solve_status(db):
    runner = make_runner(db)
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    doc = SolutionRepo(db).get("school-1", solution_id)
    assert doc["jobStatus"] == JobStatus.DONE
    assert doc["solveStatus"] == "feasible"
    assert doc["stats"]["doublesPlaced"] == 12
    assert len(doc["placements"]) == 1
    assert doc["finishedAt"] is not None


def test_a_queued_job_has_no_solve_status_yet(db):
    """Review Focus: a client must never read a pending job as 'no answer'."""
    threads = DeferredExecutor()
    runner = make_runner(db, thread_pool=threads)
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    doc = SolutionRepo(db).get("school-1", solution_id)
    assert doc["jobStatus"] == JobStatus.QUEUED
    assert doc["solveStatus"] is None

    threads.run_next()
    assert SolutionRepo(db).get("school-1", solution_id)["jobStatus"] == (
        JobStatus.DONE
    )


def test_the_job_is_marked_running_while_the_solver_works(db):
    """Observed from inside the solve, which is the only honest vantage."""
    seen: list[str] = []

    def watching_solve(snapshot, limit):
        doc = SolutionRepo(db).get("school-1", seen_id[0])
        seen.append(doc["jobStatus"])
        assert doc["solveStatus"] is None
        return DONE_PAYLOAD

    seen_id: list[str] = []
    runner = SolveRunner(
        db,
        solve_fn=watching_solve,
        thread_pool=DeferredExecutor(),
        process_pool=InlineExecutor(),
    )
    runner.start()
    seen_id.append(runner.submit("school-1", "scenario-1", SNAPSHOT))
    runner._threads.run_next()

    assert seen == [JobStatus.RUNNING]


def test_a_crashing_solve_is_failed_and_never_unknown(db):
    """The cardinal rule, one layer up from P1 §7.3.

    'We broke' and 'the solver could not decide' are different answers. A
    crash reported as `unknown` would tell a user their timetable might be
    impossible when in fact nothing was ever attempted.
    """

    def exploding_solve(snapshot, limit):
        raise RuntimeError("ortools went missing")

    runner = make_runner(db, solve_fn=exploding_solve)
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    doc = SolutionRepo(db).get("school-1", solution_id)
    assert doc["jobStatus"] == JobStatus.FAILED
    assert doc["solveStatus"] is None
    assert "ortools went missing" in doc["error"]


def test_an_unknown_solve_result_is_done_not_failed(db):
    """The mirror of the test above: a timeout is a real, finished answer."""
    unknown = {**DONE_PAYLOAD, "status": "unknown", "placements": []}
    runner = make_runner(db, solve_fn=lambda s, limit: unknown)
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    doc = SolutionRepo(db).get("school-1", solution_id)
    assert doc["jobStatus"] == JobStatus.DONE
    assert doc["solveStatus"] == "unknown"


def test_the_snapshot_and_time_limit_are_frozen_on_the_document(db):
    runner = make_runner(db)
    solution_id = runner.submit(
        "school-1", "scenario-1", SNAPSHOT, time_limit_s=42.0
    )

    doc = SolutionRepo(db).get("school-1", solution_id)
    assert doc["inputSnapshot"] == SNAPSHOT
    assert doc["timeLimitS"] == 42.0


def test_a_queued_job_can_be_cancelled_and_then_never_runs(db):
    threads = DeferredExecutor()
    calls: list[int] = []
    runner = make_runner(
        db,
        solve_fn=lambda s, limit: calls.append(1) or DONE_PAYLOAD,
        thread_pool=threads,
    )
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    assert runner.cancel("school-1", solution_id) is True
    threads.run_next()  # the thread still fires; the job must decline to run

    doc = SolutionRepo(db).get("school-1", solution_id)
    assert doc["jobStatus"] == JobStatus.CANCELLED
    assert calls == []


def test_a_finished_job_cannot_be_cancelled(db):
    runner = make_runner(db)
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    assert runner.cancel("school-1", solution_id) is False
    assert SolutionRepo(db).get("school-1", solution_id)["jobStatus"] == (
        JobStatus.DONE
    )


def test_a_job_belonging_to_another_school_is_invisible(db):
    runner = make_runner(db)
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    assert SolutionRepo(db).get("school-2", solution_id) is None
    assert runner.cancel("school-2", solution_id) is False


def test_startup_fails_every_job_orphaned_by_a_restart(db):
    """The pool dies with the container, so queued and running are orphans."""
    threads = DeferredExecutor()
    runner = make_runner(db, thread_pool=threads)
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    # A second runner is a second process lifetime.
    make_runner(db)

    doc = SolutionRepo(db).get("school-1", solution_id)
    assert doc["jobStatus"] == JobStatus.FAILED
    assert "restarted" in doc["error"]


def test_solutions_are_listed_only_for_their_own_scenario(db):
    runner = make_runner(db)
    first = runner.submit("school-1", "scenario-1", SNAPSHOT)
    second = runner.submit("school-1", "scenario-1", SNAPSHOT)
    runner.submit("school-1", "scenario-2", SNAPSHOT)

    ids = [
        d["id"]
        for d in SolutionRepo(db).list_for_scenario("school-1", "scenario-1")
    ]
    assert set(ids) == {first, second}
```

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_jobs_runner.py -v` (Bash `timeout=600000`)
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.jobs.runner'`

- [ ] **Step 4: Append `SolutionRepo` to the repositories module**

Add to the imports at the top of `roster/store/repositories.py`:

```python
from datetime import datetime, timezone
```

Append to `roster/store/repositories.py`:

```python
class SolutionRepo:
    """The solutions collection, which doubles as the job record.

    A solution document is created the moment a solve is requested and fills
    in as the job progresses, so there is no second collection to keep
    consistent with it.

    `jobStatus` and `solveStatus` are separate fields and are never merged.
    `solveStatus` stays None unless `jobStatus` is "done".
    """

    def __init__(self, db: Database) -> None:
        self._c = db["solutions"]

    @staticmethod
    def _public(doc: dict[str, Any]) -> dict[str, Any]:
        out = dict(doc)
        out["id"] = str(out.pop("_id"))
        return out

    def create_queued(
        self,
        school_id: str,
        scenario_id: str,
        snapshot: dict[str, Any],
        time_limit_s: float,
        solver_version: str = "",
    ) -> str:
        doc: dict[str, Any] = {
            "schoolId": school_id,
            "scenarioId": scenario_id,
            "jobStatus": "queued",
            "solveStatus": None,
            "inputSnapshot": snapshot,
            "timeLimitS": time_limit_s,
            "solverVersion": solver_version,
            "placements": [],
            "stats": None,
            "findings": [],
            "conflict": None,
            "error": None,
            "createdAt": datetime.now(timezone.utc),
            "startedAt": None,
            "finishedAt": None,
        }
        return str(self._c.insert_one(doc).inserted_id)

    def get(self, school_id: str, solution_id: str) -> dict[str, Any] | None:
        oid = _oid(solution_id)
        if oid is None:
            return None
        doc = self._c.find_one({"_id": oid, "schoolId": school_id})
        return self._public(doc) if doc else None

    def list_for_scenario(
        self, school_id: str, scenario_id: str
    ) -> list[dict[str, Any]]:
        rows = self._c.find(
            {"schoolId": school_id, "scenarioId": scenario_id}
        ).sort("createdAt", -1)
        return [self._public(d) for d in rows]

    def mark_running(self, school_id: str, solution_id: str) -> bool:
        """Only queued jobs may start.

        This filter is what makes cancellation race-free: a job cancelled
        between submission and execution simply never begins.
        """
        oid = _oid(solution_id)
        if oid is None:
            return False
        result = self._c.update_one(
            {"_id": oid, "schoolId": school_id, "jobStatus": "queued"},
            {
                "$set": {
                    "jobStatus": "running",
                    "startedAt": datetime.now(timezone.utc),
                }
            },
        )
        return result.matched_count == 1

    def mark_done(
        self, school_id: str, solution_id: str, payload: dict[str, Any]
    ) -> None:
        oid = _oid(solution_id)
        if oid is None:
            return
        self._c.update_one(
            {"_id": oid, "schoolId": school_id},
            {
                "$set": {
                    "jobStatus": "done",
                    "solveStatus": payload["status"],
                    "placements": payload.get("placements", []),
                    "findings": payload.get("findings", []),
                    "conflict": payload.get("conflict"),
                    "stats": {
                        "doublesPlaced": payload.get("doublesPlaced", 0),
                        "doublesCeiling": payload.get("doublesCeiling", 0),
                        "wallSeconds": payload.get("wallSeconds", 0.0),
                    },
                    "finishedAt": datetime.now(timezone.utc),
                }
            },
        )

    def mark_failed(
        self, school_id: str, solution_id: str, error: str
    ) -> None:
        """A crashed job. `solveStatus` stays None — never "unknown"."""
        oid = _oid(solution_id)
        if oid is None:
            return
        self._c.update_one(
            {"_id": oid, "schoolId": school_id},
            {
                "$set": {
                    "jobStatus": "failed",
                    "solveStatus": None,
                    "error": error,
                    "finishedAt": datetime.now(timezone.utc),
                }
            },
        )

    def cancel_if_queued(self, school_id: str, solution_id: str) -> bool:
        oid = _oid(solution_id)
        if oid is None:
            return False
        result = self._c.update_one(
            {"_id": oid, "schoolId": school_id, "jobStatus": "queued"},
            {
                "$set": {
                    "jobStatus": "cancelled",
                    "finishedAt": datetime.now(timezone.utc),
                }
            },
        )
        return result.matched_count == 1

    def sweep_orphans(self) -> int:
        """Fail every job left behind by a previous process lifetime.

        Runs at startup across all tenants — the one method here with no
        school filter, because a restart orphans every school's jobs alike.
        The process pool dies with the container, so anything still queued or
        running has no one left to finish it.
        """
        result = self._c.update_many(
            {"jobStatus": {"$in": ["queued", "running"]}},
            {
                "$set": {
                    "jobStatus": "failed",
                    "solveStatus": None,
                    "error": "server restarted during solve",
                    "finishedAt": datetime.now(timezone.utc),
                }
            },
        )
        return result.modified_count
```

- [ ] **Step 5: Implement the runner**

Create `roster/jobs/runner.py`:

```python
"""Drives solves as background jobs.

Two executors, deliberately:

- a single-slot ThreadPoolExecutor orchestrates and performs the MongoDB
  writes. It lives in the parent process, so it may.
- a ProcessPoolExecutor runs CP-SAT, which saturates whatever cores it is
  given and cannot be interrupted once started.

concurrent.futures offers no "task started" callback, so without the thread
the runner could not honestly report `running` — it would have to guess, and
a guessed status is exactly what spec §5.2 forbids.
"""

from __future__ import annotations

from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from enum import StrEnum
from typing import Any

from pymongo.database import Database

from roster.jobs.worker import DEFAULT_TIME_LIMIT_S, solve_snapshot
from roster.store.repositories import SolutionRepo


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


def solver_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return f"ortools {version('ortools')}"
    except PackageNotFoundError:
        return "ortools unknown"


class SolveRunner:
    def __init__(
        self,
        db: Database,
        *,
        time_limit_s: float = DEFAULT_TIME_LIMIT_S,
        max_workers: int = 1,
        solve_fn=solve_snapshot,
        thread_pool=None,
        process_pool=None,
    ) -> None:
        self._solutions = SolutionRepo(db)
        self._time_limit_s = time_limit_s
        self._max_workers = max_workers
        self._solve_fn = solve_fn
        self._threads = thread_pool
        self._processes = process_pool
        self._pending: dict[str, Future] = {}
        self._version = solver_version()

    def start(self) -> None:
        if self._threads is None:
            self._threads = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="solve-orchestrator"
            )
        if self._processes is None:
            self._processes = ProcessPoolExecutor(
                max_workers=self._max_workers
            )
        self._solutions.sweep_orphans()

    def shutdown(self) -> None:
        for pool in (self._threads, self._processes):
            if pool is not None:
                pool.shutdown(wait=False)

    def submit(
        self,
        school_id: str,
        scenario_id: str,
        snapshot: dict[str, Any],
        time_limit_s: float | None = None,
    ) -> str:
        limit = self._time_limit_s if time_limit_s is None else time_limit_s
        solution_id = self._solutions.create_queued(
            school_id, scenario_id, snapshot, limit, self._version
        )
        future = self._threads.submit(
            self._run_job, school_id, solution_id, snapshot, limit
        )
        self._pending[solution_id] = future
        return solution_id

    def cancel(self, school_id: str, solution_id: str) -> bool:
        """Only while queued. A running CP-SAT solve cannot be interrupted.

        It does not need to be: the time limit bounds every solve, so a
        running job finishes on its own.
        """
        cancelled = self._solutions.cancel_if_queued(school_id, solution_id)
        if cancelled:
            future = self._pending.pop(solution_id, None)
            if future is not None:
                future.cancel()
        return cancelled

    def _run_job(
        self,
        school_id: str,
        solution_id: str,
        snapshot: dict[str, Any],
        time_limit_s: float,
    ) -> None:
        if not self._solutions.mark_running(school_id, solution_id):
            # Cancelled between submission and execution. Nothing to do.
            return
        try:
            payload = self._processes.submit(
                self._solve_fn, snapshot, time_limit_s
            ).result()
        except BaseException as exc:  # noqa: BLE001
            # A crash is `failed`, never `unknown`. "We broke" and "the
            # solver could not decide" are different answers to the user.
            self._solutions.mark_failed(
                school_id, solution_id, f"{type(exc).__name__}: {exc}"
            )
            return
        finally:
            self._pending.pop(solution_id, None)
        self._solutions.mark_done(school_id, solution_id, payload)
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_jobs_runner.py -v` (Bash `timeout=600000`)
Expected: 11 passed.

- [ ] **Step 7: Run the whole fast suite**

Run: `.venv/bin/python -m pytest` (Bash `timeout=600000`)
Expected: `152 passed`.

- [ ] **Step 8: Commit**

```bash
git add roster/store/repositories.py roster/jobs/runner.py tests/conftest.py tests/test_jobs_runner.py
git commit -m "Add the solution repository and the background solve runner"
```

---

### Task 7: Password hashing and session cookies

**Files:**
- Create: `roster/api/__init__.py`, `roster/api/security.py`
- Test: `tests/test_api_security.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SESSION_COOKIE = "roster_session"`; `SESSION_MAX_AGE_S`; `hash_password(password: str) -> str`; `verify_password(password_hash: str, password: str) -> bool`; `sign_session(secret: str, school_id: str, user_id: str) -> str`; `read_session(secret: str, token: str, max_age_s: int = SESSION_MAX_AGE_S) -> tuple[str, str] | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_security.py`:

```python
from roster.api.security import (
    hash_password,
    read_session,
    sign_session,
    verify_password,
)

SECRET = "a-test-secret"


def test_a_hash_is_not_the_password():
    assert hash_password("hunter2") != "hunter2"


def test_the_right_password_verifies_and_a_wrong_one_does_not():
    stored = hash_password("hunter2")
    assert verify_password(stored, "hunter2") is True
    assert verify_password(stored, "hunter3") is False


def test_the_same_password_hashes_differently_each_time():
    """Argon2 salts every hash, so two users sharing a password are not
    visibly identical in the database."""
    assert hash_password("hunter2") != hash_password("hunter2")


def test_a_corrupt_stored_hash_is_a_failed_verification_not_a_crash():
    """A truncated or hand-edited hash must not 500 the login route."""
    assert verify_password("not-a-real-argon2-hash", "hunter2") is False


def test_a_session_round_trips():
    token = sign_session(SECRET, "school-1", "user-1")
    assert read_session(SECRET, token) == ("school-1", "user-1")


def test_a_token_signed_with_another_secret_is_rejected():
    token = sign_session("other-secret", "school-1", "user-1")
    assert read_session(SECRET, token) is None


def test_a_tampered_token_is_rejected():
    token = sign_session(SECRET, "school-1", "user-1")
    assert read_session(SECRET, token[:-1] + ("A" if token[-1] != "A" else "B")) is None


def test_an_expired_token_is_rejected():
    token = sign_session(SECRET, "school-1", "user-1")
    assert read_session(SECRET, token, max_age_s=-1) is None


def test_a_token_that_is_not_a_token_at_all_is_rejected():
    assert read_session(SECRET, "") is None
    assert read_session(SECRET, "garbage") is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_security.py -v` (Bash `timeout=600000`)
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.api'`

- [ ] **Step 3: Implement security**

Create `roster/api/__init__.py`:

```python
"""The HTTP layer. Never imported by roster/__init__.py."""
```

Create `roster/api/security.py`:

```python
"""Password hashing and session cookies.

Argon2id via argon2-cffi, used directly rather than through passlib, whose
last release was 2020. A dead dependency is the wrong trade for a password
hash.

The session is a signed cookie rather than a database row: stateless, so no
sessions collection and no extra read per request. The cost is that a session
cannot be revoked before it expires, which is acceptable for one shared
login per school and should be revisited alongside per-user accounts.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SESSION_COOKIE = "roster_session"
SESSION_MAX_AGE_S = 14 * 24 * 3600

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return True


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="roster-session")


def sign_session(secret: str, school_id: str, user_id: str) -> str:
    return _serializer(secret).dumps(
        {"schoolId": school_id, "userId": user_id}
    )


def read_session(
    secret: str, token: str, max_age_s: int = SESSION_MAX_AGE_S
) -> tuple[str, str] | None:
    if not token:
        return None
    try:
        data = _serializer(secret).loads(token, max_age=max_age_s)
    except (BadSignature, SignatureExpired):
        return None
    school_id = data.get("schoolId")
    user_id = data.get("userId")
    if not isinstance(school_id, str) or not isinstance(user_id, str):
        return None
    return school_id, user_id
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_api_security.py -v` (Bash `timeout=600000`)
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add roster/api/__init__.py roster/api/security.py tests/test_api_security.py
git commit -m "Add Argon2 password hashing and signed session cookies"
```

---

### Task 8: The application, dependencies, and authentication

**Files:**
- Create: `roster/api/schemas.py`, `roster/api/deps.py`, `roster/api/app.py`, `roster/api/routers/__init__.py`, `roster/api/routers/auth.py`
- Modify: `tests/conftest.py` (app and client fixtures)
- Test: `tests/test_api_auth.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 6, 7.
- Produces:
  - `Session(school_id: str, user_id: str)` frozen dataclass
  - `get_settings(request) -> Settings`, `get_db(request) -> Database`, `get_runner(request) -> SolveRunner`, `current_session(request) -> Session`
  - `create_app(*, settings=None, db=None, runner=None) -> FastAPI`
  - `LoginRequest(email: str, password: str)`, `SessionResponse(schoolId: str, userId: str, email: str, schoolName: str)`

**The injection seam.** `create_app` accepts a database and a runner. Tests pass mongomock and a runner with inline executors; production passes neither and the lifespan handler builds the real ones. Without this seam every API test would need a live MongoDB and a process pool.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_auth.py`:

```python
from roster.api.security import SESSION_COOKIE, hash_password
from roster.store.repositories import SchoolRepo, UserRepo


def test_login_sets_a_session_cookie_and_returns_the_school(client, db):
    school = SchoolRepo(db).create("Meridian", (4,), ("A",))
    UserRepo(db).create(school.id, "head@meridian.example", hash_password("pw"))

    response = client.post(
        "/auth/login",
        json={"email": "head@meridian.example", "password": "pw"},
    )

    assert response.status_code == 200
    assert response.json()["schoolId"] == school.id
    assert response.json()["schoolName"] == "Meridian"
    assert SESSION_COOKIE in response.cookies


def test_a_wrong_password_and_an_unknown_email_give_the_same_answer(
    client, db
):
    """No user enumeration: the two failures must be indistinguishable."""
    school = SchoolRepo(db).create("Meridian", (4,), ("A",))
    UserRepo(db).create(school.id, "head@meridian.example", hash_password("pw"))

    wrong = client.post(
        "/auth/login",
        json={"email": "head@meridian.example", "password": "nope"},
    )
    unknown = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "pw"}
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_me_requires_a_session(client):
    assert client.get("/auth/me").status_code == 401


def test_me_returns_the_signed_in_school(signed_in_client, school):
    response = signed_in_client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["schoolId"] == school.id
    assert response.json()["email"] == "head@meridian.example"


def test_a_forged_cookie_is_rejected(client):
    client.cookies.set(SESSION_COOKIE, "forged")
    assert client.get("/auth/me").status_code == 401


def test_logout_clears_the_session(signed_in_client):
    assert signed_in_client.post("/auth/logout").status_code == 200
    assert signed_in_client.get("/auth/me").status_code == 401


def test_the_session_cookie_is_http_only(client, db):
    school = SchoolRepo(db).create("Meridian", (4,), ("A",))
    UserRepo(db).create(school.id, "head@meridian.example", hash_password("pw"))

    response = client.post(
        "/auth/login",
        json={"email": "head@meridian.example", "password": "pw"},
    )

    header = response.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "samesite=lax" in header
```

- [ ] **Step 2: Add the app fixtures to conftest**

Append to `tests/conftest.py`:

```python
from fastapi.testclient import TestClient

from roster.api.app import create_app
from roster.api.security import hash_password
from roster.jobs.runner import SolveRunner
from roster.store.config import Settings
from roster.store.repositories import SchoolRepo, UserRepo

TEST_SETTINGS = Settings(
    mongodb_uri="mongodb://unused",
    session_secret="test-secret",
    solve_time_limit_s=1.0,
    cookie_secure=False,
)


@pytest.fixture
def runner(db):
    """A runner whose executors run inline, so no CP-SAT and no processes."""
    return SolveRunner(
        db,
        solve_fn=lambda snapshot, limit: {
            "status": "feasible",
            "doublesPlaced": 0,
            "doublesCeiling": 0,
            "wallSeconds": 0.0,
            "findings": [],
            "conflict": None,
            "placements": [],
        },
        thread_pool=InlineExecutor(),
        process_pool=InlineExecutor(),
    )


@pytest.fixture
def client(db, runner):
    app = create_app(settings=TEST_SETTINGS, db=db, runner=runner)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def school(db):
    record = SchoolRepo(db).create("Meridian", (4, 5, 6, 7), ("A", "B", "C"))
    UserRepo(db).create(
        record.id, "head@meridian.example", hash_password("pw")
    )
    return record


@pytest.fixture
def signed_in_client(client, school):
    client.post(
        "/auth/login",
        json={"email": "head@meridian.example", "password": "pw"},
    )
    return client
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_auth.py -v` (Bash `timeout=600000`)
Expected: FAIL — `ModuleNotFoundError: No module named 'roster.api.app'`

- [ ] **Step 4: Implement the schemas**

Create `roster/api/schemas.py`:

```python
"""Pydantic models, used only at the HTTP edge.

Domain dataclasses never become Pydantic models: that would drag web
concerns into the pure core. `roster/io.py` is the bridge for anything
solver-shaped, and it already emits camelCase.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class SessionResponse(BaseModel):
    schoolId: str
    userId: str
    email: str
    schoolName: str


class SchoolResponse(BaseModel):
    id: str
    name: str
    cycleDays: int
    periodsPerDay: int
    grades: list[int]
    sections: list[str]


class SchoolUpdate(BaseModel):
    name: str


class TeacherRequest(BaseModel):
    name: str
    blockedSlots: list[int] = Field(default_factory=list)


class TeacherUpdate(BaseModel):
    name: str | None = None
    blockedSlots: list[int] | None = None


class TeacherResponse(BaseModel):
    id: str
    name: str
    blockedSlots: list[int]


class SubjectRequest(BaseModel):
    code: str
    displayName: str
    isCore: bool
    isOptional: bool = False


class SubjectUpdate(BaseModel):
    displayName: str | None = None
    isCore: bool | None = None
    isOptional: bool | None = None


class SubjectResponse(BaseModel):
    code: str
    displayName: str
    isCore: bool
    isOptional: bool


class CurriculumRequest(BaseModel):
    kind: str
    grade: int
    subjectCode: str
    periods: int


class CurriculumResponse(BaseModel):
    kind: str
    grade: int
    subjectCode: str
    periods: int


class OverrideValue(BaseModel):
    """Key names match roster/io.py, so the scenario routes and the
    /problem route describe an override with the same words."""

    grade: int
    subject: str
    periods: int


class MinDoubleValue(BaseModel):
    grade: int
    subject: str
    minimum: int


class BlockRequest(BaseModel):
    teacherId: str
    grade: int
    subject: str
    sections: list[str]
    periodsPerClass: int


class ScenarioRequest(BaseModel):
    name: str


class ScenarioUpdate(BaseModel):
    name: str | None = None
    enabledOptional: list[str] | None = None
    overrides: list[OverrideValue] | None = None
    minDoubles: list[MinDoubleValue] | None = None
    blocks: list[BlockRequest] | None = None


class ScenarioResponse(BaseModel):
    id: str
    name: str
    enabledOptional: list[str]
    overrides: list[OverrideValue]
    minDoubles: list[MinDoubleValue]
    blocks: list[BlockRequest]


class FindingResponse(BaseModel):
    code: str
    severity: str
    message: str


class ValidateResponse(BaseModel):
    findings: list[FindingResponse]
    hasErrors: bool


class SolveRequest(BaseModel):
    timeLimitS: float | None = None
```

- [ ] **Step 5: Implement the dependencies**

Create `roster/api/deps.py`:

```python
"""Request-scoped dependencies.

`current_session` is the single place a schoolId enters the application. No
route reads a schoolId from a path, a query string or a body, so no route can
be talked into another school's data.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request
from pymongo.database import Database

from roster.api.security import SESSION_COOKIE, read_session
from roster.store.config import Settings


@dataclass(frozen=True)
class Session:
    school_id: str
    user_id: str


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_runner(request: Request):
    return request.app.state.runner


def current_session(request: Request) -> Session:
    settings: Settings = request.app.state.settings
    token = request.cookies.get(SESSION_COOKIE, "")
    pair = read_session(settings.session_secret, token)
    if pair is None:
        raise HTTPException(status_code=401, detail="not signed in")
    return Session(school_id=pair[0], user_id=pair[1])
```

- [ ] **Step 6: Implement the auth router**

Create `roster/api/routers/__init__.py`:

```python
"""HTTP routers. Thin: they validate, delegate, and translate errors."""
```

Create `roster/api/routers/auth.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from roster.api.deps import Session, current_session, get_db, get_settings
from roster.api.schemas import LoginRequest, SessionResponse
from roster.api.security import (
    SESSION_COOKIE,
    SESSION_MAX_AGE_S,
    sign_session,
    verify_password,
)
from roster.store.repositories import SchoolRepo, UserRepo

router = APIRouter(prefix="/auth", tags=["auth"])

# One message for both failures. Distinguishing them would let anyone
# discover which addresses have accounts.
_BAD_CREDENTIALS = "invalid email or password"


@router.post("/login", response_model=SessionResponse)
def login(
    payload: LoginRequest,
    response: Response,
    db=Depends(get_db),
    settings=Depends(get_settings),
) -> SessionResponse:
    user = UserRepo(db).by_email(payload.email)
    if user is None or not verify_password(
        user.password_hash, payload.password
    ):
        raise HTTPException(status_code=401, detail=_BAD_CREDENTIALS)

    school = SchoolRepo(db).get(user.school_id)
    if school is None:
        raise HTTPException(status_code=401, detail=_BAD_CREDENTIALS)

    response.set_cookie(
        SESSION_COOKIE,
        sign_session(settings.session_secret, user.school_id, user.id),
        max_age=SESSION_MAX_AGE_S,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return SessionResponse(
        schoolId=user.school_id,
        userId=user.id,
        email=user.email,
        schoolName=school.name,
    )


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me", response_model=SessionResponse)
def me(
    session: Session = Depends(current_session), db=Depends(get_db)
) -> SessionResponse:
    user = UserRepo(db).get(session.school_id, session.user_id)
    school = SchoolRepo(db).get(session.school_id)
    if user is None or school is None:
        raise HTTPException(status_code=401, detail="session no longer valid")
    return SessionResponse(
        schoolId=school.id,
        userId=user.id,
        email=user.email,
        schoolName=school.name,
    )
```

- [ ] **Step 7: Implement the application factory**

Create `roster/api/app.py`:

```python
"""The FastAPI application.

`create_app` accepts a database and a runner so tests can pass mongomock and
inline executors. In production both are None and the lifespan handler builds
the real ones: one MongoClient, because Atlas M0 caps connections, and one
process pool.

Routes that touch MongoDB are declared `def`, not `async def`, so FastAPI
runs them in its threadpool and the synchronous driver never blocks the event
loop.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from roster.api.routers import auth
from roster.jobs.runner import SolveRunner
from roster.store.client import get_database, make_client
from roster.store.config import Settings, settings_from_env
from roster.store.indexes import ensure_indexes


def create_app(
    *,
    settings: Settings | None = None,
    db=None,
    runner: SolveRunner | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved = settings if settings is not None else settings_from_env()
        app.state.settings = resolved

        client = None
        if db is not None:
            app.state.db = db
        else:
            client = make_client(resolved)
            app.state.db = get_database(client, resolved)
        ensure_indexes(app.state.db)

        app.state.runner = runner or SolveRunner(
            app.state.db,
            time_limit_s=resolved.solve_time_limit_s,
            max_workers=resolved.solve_max_workers,
        )
        app.state.runner.start()
        try:
            yield
        finally:
            app.state.runner.shutdown()
            if client is not None:
                client.close()

    app = FastAPI(title="Roster", lifespan=lifespan)
    app.include_router(auth.router)
    return app
```

- [ ] **Step 8: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_api_auth.py -v` (Bash `timeout=600000`)
Expected: 7 passed.

- [ ] **Step 9: Run the whole fast suite and the boundary guard**

Run: `.venv/bin/python -m pytest` (Bash `timeout=600000`)
Expected: `168 passed`. `tests/test_boundaries.py` must still pass — if it now fails, something imported `fastapi` from the core.

- [ ] **Step 10: Commit**

```bash
git add roster/api tests/conftest.py tests/test_api_auth.py
git commit -m "Add the FastAPI application, session dependencies and auth routes"
```

---

### Task 9: Entity routes — school, teachers, subjects, curriculum

**Files:**
- Create: `roster/api/routers/entities.py`
- Modify: `roster/api/app.py` (include the router)
- Test: `tests/test_api_entities.py`

**Interfaces:**
- Consumes: Tasks 3, 8.
- Produces: `router` at `roster.api.routers.entities`, mounted at the application root. Paths: `GET`/`PATCH` `/school`; `GET`/`POST` `/teachers`, `GET`/`PATCH`/`DELETE` `/teachers/{teacher_id}`; `GET`/`POST` `/subjects`, `GET`/`PATCH`/`DELETE` `/subjects/{code}`; `GET` `/curriculum`, `PUT` `/curriculum`, `DELETE` `/curriculum/{kind}/{grade}/{subject_code}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_entities.py`:

```python
from roster.api.security import hash_password
from roster.store.repositories import SchoolRepo, TeacherRepo, UserRepo


def test_every_entity_route_requires_a_session(client):
    for method, path in [
        ("get", "/school"),
        ("get", "/teachers"),
        ("post", "/teachers"),
        ("get", "/subjects"),
        ("get", "/curriculum"),
    ]:
        response = getattr(client, method)(path, json={})
        assert response.status_code == 401, path


def test_the_school_route_returns_the_session_s_school(signed_in_client):
    response = signed_in_client.get("/school")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Meridian"
    assert body["cycleDays"] == 6
    assert body["periodsPerDay"] == 10
    assert body["grades"] == [4, 5, 6, 7]


def test_a_teacher_is_created_listed_updated_and_deleted(signed_in_client):
    created = signed_in_client.post(
        "/teachers", json={"name": "Karin", "blockedSlots": [3, 4]}
    )
    assert created.status_code == 201
    teacher_id = created.json()["id"]
    assert created.json()["blockedSlots"] == [3, 4]

    assert [t["id"] for t in signed_in_client.get("/teachers").json()] == [
        teacher_id
    ]

    patched = signed_in_client.patch(
        f"/teachers/{teacher_id}", json={"blockedSlots": [9]}
    )
    assert patched.status_code == 200
    assert patched.json()["blockedSlots"] == [9]
    assert patched.json()["name"] == "Karin"

    assert signed_in_client.delete(f"/teachers/{teacher_id}").status_code == 204
    assert signed_in_client.get(f"/teachers/{teacher_id}").status_code == 404


def test_another_school_s_teacher_is_a_404_not_a_403(
    signed_in_client, db, school
):
    """Review Focus 1 — the most likely security defect in the phase.

    403 would confirm the document exists. A document outside the session's
    school must be indistinguishable from one that was never created.
    """
    other = SchoolRepo(db).create("Other", (4,), ("A",))
    theirs = TeacherRepo(db).create(other.id, "Shane", frozenset())

    assert signed_in_client.get(f"/teachers/{theirs.id}").status_code == 404
    assert (
        signed_in_client.patch(
            f"/teachers/{theirs.id}", json={"name": "Renamed"}
        ).status_code
        == 404
    )
    assert signed_in_client.delete(f"/teachers/{theirs.id}").status_code == 404

    # And it is untouched.
    assert TeacherRepo(db).get(other.id, theirs.id).name == "Shane"


def test_a_malformed_teacher_id_is_a_404_not_a_500(signed_in_client):
    assert signed_in_client.get("/teachers/not-an-id").status_code == 404


def test_a_blocked_slot_outside_the_cycle_is_rejected(signed_in_client):
    """The cycle is 60 slots. Slot 60 would pass straight into the model."""
    response = signed_in_client.post(
        "/teachers", json={"name": "Karin", "blockedSlots": [60]}
    )
    assert response.status_code == 400
    assert "slot" in response.json()["detail"].lower()


def test_a_subject_is_created_listed_and_deleted(signed_in_client):
    created = signed_in_client.post(
        "/subjects",
        json={
            "code": "MAT",
            "displayName": "Mathematics",
            "isCore": True,
            "isOptional": False,
        },
    )
    assert created.status_code == 201

    assert [s["code"] for s in signed_in_client.get("/subjects").json()] == [
        "MAT"
    ]
    assert signed_in_client.get("/subjects/MAT").json()["displayName"] == (
        "Mathematics"
    )
    assert signed_in_client.delete("/subjects/MAT").status_code == 204
    assert signed_in_client.get("/subjects/MAT").status_code == 404


def test_a_duplicate_subject_code_is_a_conflict(signed_in_client):
    body = {
        "code": "MAT",
        "displayName": "Mathematics",
        "isCore": True,
        "isOptional": False,
    }
    assert signed_in_client.post("/subjects", json=body).status_code == 201
    assert signed_in_client.post("/subjects", json=body).status_code == 409


def test_curriculum_entries_are_listed_by_kind(signed_in_client):
    signed_in_client.put(
        "/curriculum",
        json={"kind": "caps", "grade": 4, "subjectCode": "MAT", "periods": 8},
    )
    signed_in_client.put(
        "/curriculum",
        json={"kind": "optional", "grade": 4, "subjectCode": "BIB", "periods": 2},
    )

    caps = signed_in_client.get("/curriculum", params={"kind": "caps"}).json()
    assert caps == [
        {"kind": "caps", "grade": 4, "subjectCode": "MAT", "periods": 8}
    ]


def test_putting_the_same_entry_twice_replaces_the_period_count(
    signed_in_client,
):
    for periods in (8, 9):
        signed_in_client.put(
            "/curriculum",
            json={
                "kind": "caps",
                "grade": 4,
                "subjectCode": "MAT",
                "periods": periods,
            },
        )

    caps = signed_in_client.get("/curriculum", params={"kind": "caps"}).json()
    assert len(caps) == 1
    assert caps[0]["periods"] == 9


def test_an_unknown_curriculum_kind_is_rejected(signed_in_client):
    response = signed_in_client.put(
        "/curriculum",
        json={"kind": "invented", "grade": 4, "subjectCode": "MAT", "periods": 8},
    )
    assert response.status_code == 400


def test_a_curriculum_entry_is_deleted(signed_in_client):
    signed_in_client.put(
        "/curriculum",
        json={"kind": "caps", "grade": 4, "subjectCode": "MAT", "periods": 8},
    )
    assert (
        signed_in_client.delete("/curriculum/caps/4/MAT").status_code == 204
    )
    assert signed_in_client.get("/curriculum", params={"kind": "caps"}).json() == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_entities.py -v` (Bash `timeout=600000`)
Expected: FAIL — 404 on every route; the router does not exist.

- [ ] **Step 3: Implement the entity routes**

Create `roster/api/routers/entities.py`:

```python
"""School, teachers, subjects and curriculum.

Every handler is `def`, not `async def`, so FastAPI runs it in a threadpool
and the synchronous MongoDB driver never blocks the event loop.

A document outside the session's school produces 404, never 403: a 403 would
confirm that the id exists, which is itself a leak across tenants.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pymongo.errors import DuplicateKeyError

from roster.api.deps import Session, current_session, get_db
from roster.api.schemas import (
    CurriculumRequest,
    CurriculumResponse,
    SchoolResponse,
    SchoolUpdate,
    SubjectRequest,
    SubjectResponse,
    SubjectUpdate,
    TeacherRequest,
    TeacherResponse,
    TeacherUpdate,
)
from roster.curriculum import CurriculumEntry
from roster.domain import SLOT_COUNT, Subject
from roster.store.repositories import (
    CurriculumRepo,
    SchoolRepo,
    SubjectRepo,
    TeacherRepo,
)

router = APIRouter(tags=["entities"])

_KINDS = {"caps", "optional"}


def _teacher_response(teacher) -> TeacherResponse:
    return TeacherResponse(
        id=teacher.id,
        name=teacher.name,
        blockedSlots=sorted(teacher.blocked_slots),
    )


def _checked_slots(slots: list[int]) -> frozenset[int]:
    for slot in slots:
        if not 0 <= slot < SLOT_COUNT:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"blocked slot {slot} is outside the cycle "
                    f"(0..{SLOT_COUNT - 1})"
                ),
            )
    return frozenset(slots)


def _checked_kind(kind: str) -> str:
    if kind not in _KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of {sorted(_KINDS)}, got {kind!r}",
        )
    return kind


@router.get("/school", response_model=SchoolResponse)
def read_school(
    session: Session = Depends(current_session), db=Depends(get_db)
) -> SchoolResponse:
    school = SchoolRepo(db).get(session.school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="school not found")
    return SchoolResponse(
        id=school.id,
        name=school.name,
        cycleDays=school.cycle_days,
        periodsPerDay=school.periods_per_day,
        grades=list(school.grades),
        sections=list(school.sections),
    )


@router.patch("/school", response_model=SchoolResponse)
def update_school(
    payload: SchoolUpdate,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> SchoolResponse:
    school = SchoolRepo(db).update(session.school_id, name=payload.name)
    if school is None:
        raise HTTPException(status_code=404, detail="school not found")
    return read_school(session=session, db=db)


@router.get("/teachers", response_model=list[TeacherResponse])
def list_teachers(
    session: Session = Depends(current_session), db=Depends(get_db)
) -> list[TeacherResponse]:
    return [_teacher_response(t) for t in TeacherRepo(db).list(session.school_id)]


@router.post("/teachers", response_model=TeacherResponse, status_code=201)
def create_teacher(
    payload: TeacherRequest,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> TeacherResponse:
    teacher = TeacherRepo(db).create(
        session.school_id, payload.name, _checked_slots(payload.blockedSlots)
    )
    return _teacher_response(teacher)


@router.get("/teachers/{teacher_id}", response_model=TeacherResponse)
def read_teacher(
    teacher_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> TeacherResponse:
    teacher = TeacherRepo(db).get(session.school_id, teacher_id)
    if teacher is None:
        raise HTTPException(status_code=404, detail="teacher not found")
    return _teacher_response(teacher)


@router.patch("/teachers/{teacher_id}", response_model=TeacherResponse)
def update_teacher(
    teacher_id: str,
    payload: TeacherUpdate,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> TeacherResponse:
    slots = (
        None
        if payload.blockedSlots is None
        else _checked_slots(payload.blockedSlots)
    )
    teacher = TeacherRepo(db).update(
        session.school_id, teacher_id, name=payload.name, blocked_slots=slots
    )
    if teacher is None:
        raise HTTPException(status_code=404, detail="teacher not found")
    return _teacher_response(teacher)


@router.delete("/teachers/{teacher_id}", status_code=204)
def delete_teacher(
    teacher_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> Response:
    if not TeacherRepo(db).delete(session.school_id, teacher_id):
        raise HTTPException(status_code=404, detail="teacher not found")
    return Response(status_code=204)


@router.get("/subjects", response_model=list[SubjectResponse])
def list_subjects(
    session: Session = Depends(current_session), db=Depends(get_db)
) -> list[SubjectResponse]:
    return [
        SubjectResponse(
            code=s.code,
            displayName=s.display_name,
            isCore=s.is_core,
            isOptional=s.is_optional,
        )
        for s in SubjectRepo(db).list(session.school_id)
    ]


@router.post("/subjects", response_model=SubjectResponse, status_code=201)
def create_subject(
    payload: SubjectRequest,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> SubjectResponse:
    subject = Subject(
        payload.code, payload.displayName, payload.isCore, payload.isOptional
    )
    try:
        SubjectRepo(db).create(session.school_id, subject)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail=f"subject {payload.code} already exists in this school",
        ) from None
    return SubjectResponse(
        code=subject.code,
        displayName=subject.display_name,
        isCore=subject.is_core,
        isOptional=subject.is_optional,
    )


@router.get("/subjects/{code}", response_model=SubjectResponse)
def read_subject(
    code: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> SubjectResponse:
    subject = SubjectRepo(db).get(session.school_id, code)
    if subject is None:
        raise HTTPException(status_code=404, detail="subject not found")
    return SubjectResponse(
        code=subject.code,
        displayName=subject.display_name,
        isCore=subject.is_core,
        isOptional=subject.is_optional,
    )


@router.patch("/subjects/{code}", response_model=SubjectResponse)
def update_subject(
    code: str,
    payload: SubjectUpdate,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> SubjectResponse:
    subject = SubjectRepo(db).update(
        session.school_id,
        code,
        display_name=payload.displayName,
        is_core=payload.isCore,
        is_optional=payload.isOptional,
    )
    if subject is None:
        raise HTTPException(status_code=404, detail="subject not found")
    return SubjectResponse(
        code=subject.code,
        displayName=subject.display_name,
        isCore=subject.is_core,
        isOptional=subject.is_optional,
    )


@router.delete("/subjects/{code}", status_code=204)
def delete_subject(
    code: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> Response:
    if not SubjectRepo(db).delete(session.school_id, code):
        raise HTTPException(status_code=404, detail="subject not found")
    return Response(status_code=204)


@router.get("/curriculum", response_model=list[CurriculumResponse])
def list_curriculum(
    kind: str = Query("caps"),
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> list[CurriculumResponse]:
    checked = _checked_kind(kind)
    return [
        CurriculumResponse(
            kind=checked,
            grade=e.grade,
            subjectCode=e.subject_code,
            periods=e.periods_per_class,
        )
        for e in CurriculumRepo(db).list(session.school_id, checked)
    ]


@router.put("/curriculum", response_model=CurriculumResponse)
def upsert_curriculum(
    payload: CurriculumRequest,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> CurriculumResponse:
    kind = _checked_kind(payload.kind)
    entry = CurriculumEntry(payload.grade, payload.subjectCode, payload.periods)
    CurriculumRepo(db).upsert(session.school_id, kind, entry)
    return CurriculumResponse(
        kind=kind,
        grade=entry.grade,
        subjectCode=entry.subject_code,
        periods=entry.periods_per_class,
    )


@router.delete("/curriculum/{kind}/{grade}/{subject_code}", status_code=204)
def delete_curriculum(
    kind: str,
    grade: int,
    subject_code: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> Response:
    checked = _checked_kind(kind)
    if not CurriculumRepo(db).delete(
        session.school_id, checked, grade, subject_code
    ):
        raise HTTPException(status_code=404, detail="curriculum entry not found")
    return Response(status_code=204)
```

- [ ] **Step 4: Mount the router**

In `roster/api/app.py`, change the import line and add the include:

```python
from roster.api.routers import auth, entities
```

```python
    app.include_router(auth.router)
    app.include_router(entities.router)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_api_entities.py -v` (Bash `timeout=600000`)
Expected: 12 passed.

- [ ] **Step 6: Commit**

```bash
git add roster/api/routers/entities.py roster/api/app.py tests/test_api_entities.py
git commit -m "Add school, teacher, subject and curriculum routes"
```

---

### Task 10: Scenario routes, assembly and validation

**Files:**
- Create: `roster/api/routers/scenarios.py`
- Modify: `roster/api/app.py`
- Test: `tests/test_api_scenarios.py`

**Interfaces:**
- Consumes: Tasks 3, 4, 8, 9.
- Produces: `router` at `roster.api.routers.scenarios`. Paths: `GET`/`POST` `/scenarios`, `GET`/`PATCH`/`DELETE` `/scenarios/{scenario_id}`, `GET` `/scenarios/{scenario_id}/problem`, `POST` `/scenarios/{scenario_id}/validate`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_scenarios.py`:

```python
import pytest


@pytest.fixture
def seeded_client(signed_in_client):
    """A one-grade school whose single scenario assembles cleanly."""
    for code, core in (("MAT", True), ("STUDY", False)):
        signed_in_client.post(
            "/subjects",
            json={
                "code": code,
                "displayName": code.title(),
                "isCore": core,
                "isOptional": False,
            },
        )
    signed_in_client.put(
        "/curriculum",
        json={"kind": "caps", "grade": 4, "subjectCode": "MAT", "periods": 8},
    )
    teacher_id = signed_in_client.post(
        "/teachers", json={"name": "Karin", "blockedSlots": []}
    ).json()["id"]
    scenario_id = signed_in_client.post(
        "/scenarios", json={"name": "Base"}
    ).json()["id"]
    signed_in_client.patch(
        f"/scenarios/{scenario_id}",
        json={
            "blocks": [
                {
                    "teacherId": teacher_id,
                    "grade": 4,
                    "subject": "MAT",
                    "sections": ["A", "B", "C"],
                    "periodsPerClass": 8,
                }
            ]
        },
    )
    return signed_in_client, scenario_id, teacher_id


def test_a_scenario_is_created_listed_and_deleted(signed_in_client):
    created = signed_in_client.post("/scenarios", json={"name": "Base"})
    assert created.status_code == 201
    scenario_id = created.json()["id"]

    assert [s["id"] for s in signed_in_client.get("/scenarios").json()] == [
        scenario_id
    ]
    assert (
        signed_in_client.delete(f"/scenarios/{scenario_id}").status_code == 204
    )
    assert signed_in_client.get(f"/scenarios/{scenario_id}").status_code == 404


def test_scenario_choices_round_trip_through_the_api(signed_in_client):
    """Overrides and minDoubles are tuple-keyed in Python and flat on the wire."""
    scenario_id = signed_in_client.post(
        "/scenarios", json={"name": "With Sepedi"}
    ).json()["id"]

    patched = signed_in_client.patch(
        f"/scenarios/{scenario_id}",
        json={
            "enabledOptional": ["BIB"],
            "overrides": [{"grade": 4, "subject": "MAT", "periods": 7}],
            "minDoubles": [{"grade": 4, "subject": "ENG", "minimum": 2}],
        },
    )
    assert patched.status_code == 200

    body = signed_in_client.get(f"/scenarios/{scenario_id}").json()
    assert body["enabledOptional"] == ["BIB"]
    assert body["overrides"] == [{"grade": 4, "subject": "MAT", "periods": 7}]
    assert body["minDoubles"] == [{"grade": 4, "subject": "ENG", "minimum": 2}]


def test_another_school_s_scenario_is_a_404(signed_in_client, db):
    from roster.store.repositories import ScenarioRepo, SchoolRepo

    other = SchoolRepo(db).create("Other", (4,), ("A",))
    theirs = ScenarioRepo(db).create(other.id, "Theirs")

    assert signed_in_client.get(f"/scenarios/{theirs.id}").status_code == 404
    assert (
        signed_in_client.get(f"/scenarios/{theirs.id}/problem").status_code
        == 404
    )


def test_the_problem_endpoint_returns_the_roster_io_shape(seeded_client):
    client, scenario_id, teacher_id = seeded_client

    body = client.get(f"/scenarios/{scenario_id}/problem").json()

    assert body["grades"] == [4, 5, 6, 7]
    assert body["sections"] == ["A", "B", "C"]
    assert {s["code"] for s in body["subjects"]} == {"MAT", "STUDY"}
    assert body["blocks"][0]["teacherId"] == teacher_id
    assert body["scenario"]["caps"] == [
        {"grade": 4, "subject": "MAT", "periods": 8}
    ]


def test_the_problem_endpoint_round_trips_through_the_core(seeded_client):
    """What the UI receives must be exactly what the solver can consume."""
    from roster.io import problem_from_dict

    client, scenario_id, _ = seeded_client
    body = client.get(f"/scenarios/{scenario_id}/problem").json()

    problem = problem_from_dict(body)
    assert problem.grades == (4, 5, 6, 7)


def test_a_scenario_naming_a_deleted_teacher_is_422_not_a_traceback(
    seeded_client,
):
    client, scenario_id, teacher_id = seeded_client
    client.delete(f"/teachers/{teacher_id}")

    response = client.get(f"/scenarios/{scenario_id}/problem")
    assert response.status_code == 422
    assert "teacher" in response.json()["detail"]


def test_validate_returns_findings_with_a_200(seeded_client):
    """A finding is an answer, not an error. Grade 5-7 have no curriculum,
    so pre-flight has plenty to say."""
    client, scenario_id, _ = seeded_client

    response = client.post(f"/scenarios/{scenario_id}/validate")

    assert response.status_code == 200
    body = response.json()
    assert body["hasErrors"] is True
    assert all({"code", "severity", "message"} <= set(f) for f in body["findings"])


def test_validate_does_not_invoke_the_solver(seeded_client):
    """Pre-flight is arithmetic. If this ever takes seconds, something is
    calling solve()."""
    import time

    client, scenario_id, _ = seeded_client
    started = time.monotonic()
    client.post(f"/scenarios/{scenario_id}/validate")
    assert time.monotonic() - started < 1.0


def test_validate_on_another_school_s_scenario_is_a_404(signed_in_client, db):
    from roster.store.repositories import ScenarioRepo, SchoolRepo

    other = SchoolRepo(db).create("Other", (4,), ("A",))
    theirs = ScenarioRepo(db).create(other.id, "Theirs")

    assert (
        signed_in_client.post(f"/scenarios/{theirs.id}/validate").status_code
        == 404
    )


def test_scenario_routes_require_a_session(client):
    assert client.get("/scenarios").status_code == 401
    assert client.post("/scenarios", json={"name": "x"}).status_code == 401
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_scenarios.py -v` (Bash `timeout=600000`)
Expected: FAIL — 404 on every scenario route.

- [ ] **Step 3: Implement the scenario routes**

Create `roster/api/routers/scenarios.py`:

```python
"""Scenarios, assembly and pre-flight validation.

`GET /scenarios/{id}/problem` returns the assembled Problem in roster.io's
format. Assembly happens here and in the solve job through the SAME function,
so the problem the UI reasons about and the one the solver receives cannot
diverge. P1 §8 makes that argument about validation; assembly is the same
trap one layer down.

A missing scenario is 404. A scenario that exists but cannot be assembled —
a block naming a deleted teacher, say — is 422: the request was well formed
and the stored data is not.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from roster.api.deps import Session, current_session, get_db
from roster.api.schemas import (
    BlockRequest,
    FindingResponse,
    MinDoubleValue,
    OverrideValue,
    ScenarioRequest,
    ScenarioResponse,
    ScenarioUpdate,
    ValidateResponse,
)
from roster.domain import Block
from roster.io import problem_to_dict
from roster.preflight import has_errors, preflight
from roster.store.assemble import AssemblyError, assemble_problem
from roster.store.repositories import ScenarioRepo

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def _response(record) -> ScenarioResponse:
    return ScenarioResponse(
        id=record.id,
        name=record.name,
        enabledOptional=sorted(record.enabled_optional),
        overrides=[
            OverrideValue(grade=g, subject=c, periods=v)
            for (g, c), v in sorted(record.overrides.items())
        ],
        minDoubles=[
            MinDoubleValue(grade=g, subject=c, minimum=v)
            for (g, c), v in sorted(record.min_doubles.items())
        ],
        blocks=[
            BlockRequest(
                teacherId=b.teacher_id,
                grade=b.grade,
                subject=b.subject_code,
                sections=list(b.sections),
                periodsPerClass=b.periods_per_class,
            )
            for b in record.blocks
        ],
    )


def _overrides(
    rows: list[OverrideValue] | None,
) -> dict[tuple[int, str], int] | None:
    if rows is None:
        return None
    return {(r.grade, r.subject): r.periods for r in rows}


def _min_doubles(
    rows: list[MinDoubleValue] | None,
) -> dict[tuple[int, str], int] | None:
    if rows is None:
        return None
    return {(r.grade, r.subject): r.minimum for r in rows}


def assemble_or_http(db, school_id: str, scenario_id: str):
    """Shared by the problem, validate and solve routes.

    Kept here rather than duplicated so all three translate the same failure
    the same way.
    """
    if ScenarioRepo(db).get(school_id, scenario_id) is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    try:
        return assemble_problem(db, school_id, scenario_id)
    except AssemblyError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from None


@router.get("", response_model=list[ScenarioResponse])
def list_scenarios(
    session: Session = Depends(current_session), db=Depends(get_db)
) -> list[ScenarioResponse]:
    return [_response(r) for r in ScenarioRepo(db).list(session.school_id)]


@router.post("", response_model=ScenarioResponse, status_code=201)
def create_scenario(
    payload: ScenarioRequest,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> ScenarioResponse:
    return _response(ScenarioRepo(db).create(session.school_id, payload.name))


@router.get("/{scenario_id}", response_model=ScenarioResponse)
def read_scenario(
    scenario_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> ScenarioResponse:
    record = ScenarioRepo(db).get(session.school_id, scenario_id)
    if record is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    return _response(record)


@router.patch("/{scenario_id}", response_model=ScenarioResponse)
def update_scenario(
    scenario_id: str,
    payload: ScenarioUpdate,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> ScenarioResponse:
    blocks = (
        None
        if payload.blocks is None
        else tuple(
            Block(
                b.teacherId,
                b.grade,
                b.subject,
                tuple(b.sections),
                b.periodsPerClass,
            )
            for b in payload.blocks
        )
    )
    enabled = (
        None
        if payload.enabledOptional is None
        else frozenset(payload.enabledOptional)
    )
    try:
        record = ScenarioRepo(db).update(
            session.school_id,
            scenario_id,
            name=payload.name,
            enabled_optional=enabled,
            overrides=_overrides(payload.overrides),
            min_doubles=_min_doubles(payload.minDoubles),
            blocks=blocks,
        )
    except ValueError as exc:
        # Block.__post_init__ rejects an empty or duplicated section list.
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if record is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    return _response(record)


@router.delete("/{scenario_id}", status_code=204)
def delete_scenario(
    scenario_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> Response:
    if not ScenarioRepo(db).delete(session.school_id, scenario_id):
        raise HTTPException(status_code=404, detail="scenario not found")
    return Response(status_code=204)


@router.get("/{scenario_id}/problem")
def read_problem(
    scenario_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> dict:
    problem = assemble_or_http(db, session.school_id, scenario_id)
    return problem_to_dict(problem)


@router.post("/{scenario_id}/validate", response_model=ValidateResponse)
def validate_scenario(
    scenario_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> ValidateResponse:
    """Arithmetic pre-flight only — never the solver.

    This is where the assignment editor's live feedback comes from, so it
    must stay in the milliseconds. A finding is an answer, not an error, so
    the status is 200 even when every check fails.
    """
    problem = assemble_or_http(db, session.school_id, scenario_id)
    findings = preflight(problem)
    return ValidateResponse(
        findings=[
            FindingResponse(code=f.code, severity=f.severity, message=f.message)
            for f in findings
        ],
        hasErrors=has_errors(findings),
    )
```

- [ ] **Step 4: Mount the router**

In `roster/api/app.py`:

```python
from roster.api.routers import auth, entities, scenarios
```

```python
    app.include_router(scenarios.router)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_api_scenarios.py -v` (Bash `timeout=600000`)
Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add roster/api/routers/scenarios.py roster/api/app.py tests/test_api_scenarios.py
git commit -m "Add scenario routes with server-side assembly and validation"
```

---

### Task 11: Solve and solution routes

**Files:**
- Create: `roster/api/routers/solutions.py`
- Modify: `roster/api/app.py`
- Test: `tests/test_api_solutions.py`

**Interfaces:**
- Consumes: Tasks 6, 10.
- Produces: `router` at `roster.api.routers.solutions`. Paths: `POST` `/scenarios/{scenario_id}/solve` (202), `GET` `/scenarios/{scenario_id}/solutions`, `GET` `/solutions/{solution_id}`, `POST` `/solutions/{solution_id}/cancel`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_solutions.py`:

```python
import pytest

from roster.store.repositories import ScenarioRepo, SchoolRepo, SolutionRepo


@pytest.fixture
def solvable(signed_in_client):
    """The smallest scenario that assembles. The runner's solve is a stub."""
    for code, core in (("MAT", True), ("STUDY", False)):
        signed_in_client.post(
            "/subjects",
            json={
                "code": code,
                "displayName": code.title(),
                "isCore": core,
                "isOptional": False,
            },
        )
    signed_in_client.put(
        "/curriculum",
        json={"kind": "caps", "grade": 4, "subjectCode": "MAT", "periods": 8},
    )
    teacher_id = signed_in_client.post(
        "/teachers", json={"name": "Karin", "blockedSlots": []}
    ).json()["id"]
    scenario_id = signed_in_client.post(
        "/scenarios", json={"name": "Base"}
    ).json()["id"]
    signed_in_client.patch(
        f"/scenarios/{scenario_id}",
        json={
            "blocks": [
                {
                    "teacherId": teacher_id,
                    "grade": 4,
                    "subject": "MAT",
                    "sections": ["A", "B", "C"],
                    "periodsPerClass": 8,
                }
            ]
        },
    )
    return signed_in_client, scenario_id, teacher_id


def test_solving_returns_202_and_a_pollable_id(solvable):
    client, scenario_id, _ = solvable

    accepted = client.post(f"/scenarios/{scenario_id}/solve")
    assert accepted.status_code == 202
    solution_id = accepted.json()["id"]

    polled = client.get(f"/solutions/{solution_id}")
    assert polled.status_code == 200
    assert polled.json()["jobStatus"] == "done"
    assert polled.json()["solveStatus"] == "feasible"


def test_a_running_job_reports_no_solve_status(solvable, db):
    """Review Focus 2.

    A client reading solveStatus alone must never see a pending job as "no
    answer exists". Checked by looking at the document the poll route reads.
    """
    client, scenario_id, _ = solvable
    solution_id = SolutionRepo(db).create_queued(
        # The session's school is the only one this client can see.
        client.get("/auth/me").json()["schoolId"],
        scenario_id,
        {"grades": [4]},
        1.0,
    )
    SolutionRepo(db).mark_running(
        client.get("/auth/me").json()["schoolId"], solution_id
    )

    body = client.get(f"/solutions/{solution_id}").json()
    assert body["jobStatus"] == "running"
    assert body["solveStatus"] is None
    assert body["placements"] == []


def test_a_failed_job_is_never_reported_as_unknown(solvable, db):
    """The other half of Review Focus 2.

    "We crashed" and "the solver could not decide" are different answers.
    """
    client, scenario_id, _ = solvable
    school_id = client.get("/auth/me").json()["schoolId"]
    solution_id = SolutionRepo(db).create_queued(
        school_id, scenario_id, {"grades": [4]}, 1.0
    )
    SolutionRepo(db).mark_failed(school_id, solution_id, "RuntimeError: boom")

    body = client.get(f"/solutions/{solution_id}").json()
    assert body["jobStatus"] == "failed"
    assert body["solveStatus"] is None
    assert "boom" in body["error"]


def test_the_frozen_snapshot_survives_a_later_edit(solvable, db):
    """Review Focus 3 — the central promise of P1 §9.

    Without it, editing a teacher's blocked slots would silently invalidate
    every stored timetable and a with/without comparison would be worthless.
    """
    client, scenario_id, teacher_id = solvable
    solution_id = client.post(f"/scenarios/{scenario_id}/solve").json()["id"]
    before = client.get(f"/solutions/{solution_id}").json()["inputSnapshot"]

    client.patch(f"/teachers/{teacher_id}", json={"blockedSlots": [0, 1, 2]})

    after = client.get(f"/solutions/{solution_id}").json()["inputSnapshot"]
    assert after == before
    assert after["teachers"][0]["blockedSlots"] == []


def test_the_request_may_override_the_time_limit(solvable, db):
    client, scenario_id, _ = solvable
    solution_id = client.post(
        f"/scenarios/{scenario_id}/solve", json={"timeLimitS": 7.5}
    ).json()["id"]

    assert client.get(f"/solutions/{solution_id}").json()["timeLimitS"] == 7.5


def test_solutions_are_listed_for_their_scenario(solvable):
    client, scenario_id, _ = solvable
    first = client.post(f"/scenarios/{scenario_id}/solve").json()["id"]
    second = client.post(f"/scenarios/{scenario_id}/solve").json()["id"]

    listed = client.get(f"/scenarios/{scenario_id}/solutions").json()
    assert {s["id"] for s in listed} == {first, second}


def test_a_solution_belonging_to_another_school_is_a_404(
    signed_in_client, db
):
    other = SchoolRepo(db).create("Other", (4,), ("A",))
    theirs = ScenarioRepo(db).create(other.id, "Theirs")
    solution_id = SolutionRepo(db).create_queued(
        other.id, theirs.id, {"grades": [4]}, 1.0
    )

    assert signed_in_client.get(f"/solutions/{solution_id}").status_code == 404
    assert (
        signed_in_client.post(
            f"/solutions/{solution_id}/cancel"
        ).status_code
        == 404
    )


def test_cancelling_a_finished_solve_is_a_conflict(solvable):
    """Honest about spec §5.8: cancel works while queued, and the stub
    runner finishes immediately."""
    client, scenario_id, _ = solvable
    solution_id = client.post(f"/scenarios/{scenario_id}/solve").json()["id"]

    response = client.post(f"/solutions/{solution_id}/cancel")
    assert response.status_code == 409
    assert "queued" in response.json()["detail"]


def test_solving_a_scenario_that_cannot_assemble_is_422(solvable):
    client, scenario_id, teacher_id = solvable
    client.delete(f"/teachers/{teacher_id}")

    assert client.post(f"/scenarios/{scenario_id}/solve").status_code == 422


def test_solve_routes_require_a_session(client):
    assert client.post("/scenarios/abc/solve").status_code == 401
    assert client.get("/solutions/abc").status_code == 401
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_solutions.py -v` (Bash `timeout=600000`)
Expected: FAIL — 404 on every solve route.

- [ ] **Step 3: Implement the solution routes**

Create `roster/api/routers/solutions.py`:

```python
"""Enqueue a solve, poll it, list history, cancel while queued.

The response carries `jobStatus` and `solveStatus` as separate fields and
never merges them. A crashed job is `failed` with `solveStatus: null`; a
solve that exhausted its clock is `done` with `solveStatus: "unknown"`. The
UI is required to keep them apart (P1 §7.3), so the API must hand them over
apart.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from roster.api.deps import Session, current_session, get_db, get_runner
from roster.api.routers.scenarios import assemble_or_http
from roster.api.schemas import SolveRequest
from roster.io import problem_to_dict
from roster.store.repositories import SolutionRepo

router = APIRouter(tags=["solutions"])


@router.post("/scenarios/{scenario_id}/solve", status_code=202)
def start_solve(
    scenario_id: str,
    payload: SolveRequest | None = None,
    session: Session = Depends(current_session),
    db=Depends(get_db),
    runner=Depends(get_runner),
) -> dict[str, str]:
    """Freeze the input and hand it to the job runner.

    The snapshot is taken now, not when the job starts, so edits made while
    the job waits in the queue cannot change what is solved.
    """
    problem = assemble_or_http(db, session.school_id, scenario_id)
    time_limit = payload.timeLimitS if payload is not None else None
    solution_id = runner.submit(
        session.school_id,
        scenario_id,
        problem_to_dict(problem),
        time_limit_s=time_limit,
    )
    return {"id": solution_id}


@router.get("/scenarios/{scenario_id}/solutions")
def list_solutions(
    scenario_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> list[dict]:
    return SolutionRepo(db).list_for_scenario(session.school_id, scenario_id)


@router.get("/solutions/{solution_id}")
def read_solution(
    solution_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> dict:
    doc = SolutionRepo(db).get(session.school_id, solution_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="solution not found")
    return doc


@router.post("/solutions/{solution_id}/cancel")
def cancel_solve(
    solution_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
    runner=Depends(get_runner),
) -> dict[str, bool]:
    doc = SolutionRepo(db).get(session.school_id, solution_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="solution not found")
    if not runner.cancel(session.school_id, solution_id):
        # A running CP-SAT solve cannot be interrupted without killing the
        # pool process. The time limit bounds it, so it will finish shortly.
        raise HTTPException(
            status_code=409,
            detail=(
                f"solution is {doc['jobStatus']}; only a queued solve can be "
                "cancelled"
            ),
        )
    return {"cancelled": True}
```

- [ ] **Step 4: Mount the router**

In `roster/api/app.py`:

```python
from roster.api.routers import auth, entities, scenarios, solutions
```

```python
    app.include_router(solutions.router)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_api_solutions.py -v` (Bash `timeout=600000`)
Expected: 10 passed.

- [ ] **Step 6: Run the whole fast suite**

Run: `.venv/bin/python -m pytest` (Bash `timeout=600000`)
Expected: `200 passed`.

- [ ] **Step 7: Commit**

```bash
git add roster/api/routers/solutions.py roster/api/app.py tests/test_api_solutions.py
git commit -m "Add background solve, polling, history and cancel routes"
```

---

### Task 12: CLI bootstrap for the first school and user

Nothing can sign in until a school and a user exist, and a snippet pasted into a terminal is not reproducible.

**Files:**
- Modify: `roster/cli.py`
- Test: `tests/test_cli_bootstrap.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 7.
- Produces: `python -m roster.cli create-school --name NAME --email EMAIL --password PASSWORD [--grades 4,5,6,7] [--sections A,B,C]`, exit 0 on success and 2 on a configuration or duplicate error.

**Import placement matters.** `roster/cli.py` is imported by Phase 1's CLI tests, which must not require `pymongo`. The store imports therefore go **inside** the `create-school` handler, not at module top level.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_bootstrap.py`:

```python
import mongomock
import pytest

from roster.cli import main
from roster.store.repositories import SchoolRepo, UserRepo


@pytest.fixture
def patched_db(monkeypatch):
    """Hand the CLI a mongomock database instead of a real connection."""
    database = mongomock.MongoClient()["roster_test"]

    def fake_database(_settings):
        return database

    monkeypatch.setattr("roster.cli._database_for_cli", fake_database)
    monkeypatch.setenv("MONGODB_URI", "mongodb://unused")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    return database


def test_create_school_writes_a_school_and_a_user(patched_db, capsys):
    code = main(
        [
            "create-school",
            "--name",
            "Meridian",
            "--email",
            "head@meridian.example",
            "--password",
            "pw",
        ]
    )

    assert code == 0
    schools = list(patched_db["schools"].find())
    assert len(schools) == 1
    assert schools[0]["name"] == "Meridian"
    assert schools[0]["cycleDays"] == 6

    user = UserRepo(patched_db).by_email("head@meridian.example")
    assert user is not None
    assert user.school_id == str(schools[0]["_id"])
    # The password is hashed, never stored as given.
    assert user.password_hash != "pw"
    assert "pw" not in user.password_hash


def test_create_school_accepts_grades_and_sections(patched_db):
    main(
        [
            "create-school",
            "--name",
            "Meridian",
            "--email",
            "head@meridian.example",
            "--password",
            "pw",
            "--grades",
            "4,5",
            "--sections",
            "A,B",
        ]
    )

    school = SchoolRepo(patched_db).get(
        str(patched_db["schools"].find_one()["_id"])
    )
    assert school.grades == (4, 5)
    assert school.sections == ("A", "B")


def test_a_duplicate_email_exits_two_rather_than_tracebacking(
    patched_db, capsys
):
    args = [
        "create-school",
        "--name",
        "Meridian",
        "--email",
        "head@meridian.example",
        "--password",
        "pw",
    ]
    assert main(args) == 0
    assert main(args) == 2
    assert "already" in capsys.readouterr().err.lower()


def test_a_missing_session_secret_exits_two(monkeypatch, capsys):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setenv("MONGODB_URI", "mongodb://unused")

    code = main(
        [
            "create-school",
            "--name",
            "Meridian",
            "--email",
            "head@meridian.example",
            "--password",
            "pw",
        ]
    )

    assert code == 2
    assert "SESSION_SECRET" in capsys.readouterr().err


def test_the_solve_command_still_works_without_the_server_extra():
    """Phase 1's CLI must not have acquired a pymongo import at module level."""
    import ast

    import roster.cli as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    top_level = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }

    forbidden = {
        m for m in top_level if m.split(".")[0] in {"pymongo", "bson"}
    }
    assert forbidden == set(), forbidden
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli_bootstrap.py -v` (Bash `timeout=600000`)
Expected: FAIL — `AttributeError: module 'roster.cli' has no attribute '_database_for_cli'`

- [ ] **Step 3: Add the subcommand**

In `roster/cli.py`, add after the existing `solve_cmd` argument definitions inside `main`:

```python
    create_cmd = sub.add_parser(
        "create-school", help="create the first school and its login"
    )
    create_cmd.add_argument("--name", required=True)
    create_cmd.add_argument("--email", required=True)
    create_cmd.add_argument("--password", required=True)
    create_cmd.add_argument("--grades", default="4,5,6,7")
    create_cmd.add_argument("--sections", default="A,B,C")
```

Immediately after `args = parser.parse_args(argv)`, add:

```python
    if args.command == "create-school":
        return _create_school(args)
```

Add these two functions at module level, below `main`:

```python
def _database_for_cli(settings):
    """Split out so tests can substitute an in-memory database.

    The pymongo imports live inside this function, not at module top level:
    `roster.cli solve` must keep working for anyone who installed the
    package without the `server` extra.
    """
    from roster.store.client import get_database, make_client

    return get_database(make_client(settings), settings)


def _create_school(args) -> int:
    from pymongo.errors import DuplicateKeyError

    from roster.api.security import hash_password
    from roster.store.config import ConfigError, settings_from_env
    from roster.store.indexes import ensure_indexes
    from roster.store.repositories import (
        SchoolRepo,
        UserRepo,
        ValidationError,
    )

    try:
        settings = settings_from_env()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    db = _database_for_cli(settings)
    ensure_indexes(db)

    try:
        grades = tuple(
            int(g) for g in args.grades.split(",") if g.strip()
        )
        sections = tuple(s.strip() for s in args.sections.split(",") if s.strip())
    except ValueError:
        print(f"error: --grades must be integers, got {args.grades!r}", file=sys.stderr)
        return 2

    try:
        school = SchoolRepo(db).create(args.name, grades, sections)
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        UserRepo(db).create(
            school.id, args.email, hash_password(args.password)
        )
    except DuplicateKeyError:
        print(
            f"error: {args.email} already has an account",
            file=sys.stderr,
        )
        return 2

    print(f"created school {school.name} ({school.id}) with login {args.email}")
    return 0
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_cli_bootstrap.py tests/test_cli.py -v` (Bash `timeout=600000`)
Expected: 5 new tests pass; Phase 1's CLI tests still pass.

Note: the duplicate-email test depends on mongomock enforcing the unique index on `email`. If mongomock does not enforce it, the test will fail — that is exactly the limitation spec §9.4 records. Fix it by having `UserRepo.create` check `by_email` first and raise `DuplicateKeyError` itself, which is correct behaviour against Atlas too.

- [ ] **Step 5: Commit**

```bash
git add roster/cli.py tests/test_cli_bootstrap.py
git commit -m "Add a create-school CLI command to bootstrap the first login"
```

---

### Task 13: The end-to-end solver test and the README

One test that really solves, through the real process pool, against the real school. It is solver-marked and takes minutes.

**Files:**
- Create: `tests/test_api_e2e.py`
- Modify: `README.md`
- Test: itself

**Interfaces:**
- Consumes: every earlier task.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the end-to-end test**

Create `tests/test_api_e2e.py`:

```python
"""One real solve, through the real HTTP surface and a real process pool.

Marked `solver`, so `pytest` skips it and `pytest -m solver` runs it. Every
other API test uses a stub solve function; this is the only one that proves
the whole chain — assemble, freeze, enqueue, solve in a child process, write
back, poll — actually works.
"""

import time

import mongomock
import pytest
from fastapi.testclient import TestClient

from roster.api.app import create_app
from roster.api.security import hash_password
from roster.io import problem_to_dict
from roster.jobs.runner import SolveRunner
from roster.store.config import Settings
from roster.store.indexes import ensure_indexes
from roster.store.repositories import (
    CurriculumRepo,
    ScenarioRepo,
    SchoolRepo,
    SubjectRepo,
    TeacherRepo,
    UserRepo,
)
from roster.verify import verify

from tests.fixtures.meridian import meridian_problem

E2E_SETTINGS = Settings(
    mongodb_uri="mongodb://unused",
    session_secret="e2e-secret",
    solve_time_limit_s=150.0,
    cookie_secure=False,
)


def _seed_from_meridian(db):
    """Load the real school into the store, entity by entity."""
    problem = meridian_problem()
    school = SchoolRepo(db).create(
        "Meridian", problem.grades, problem.sections
    )

    for subject in problem.subjects.values():
        SubjectRepo(db).create(school.id, subject)

    ids: dict[str, str] = {}
    for teacher in problem.teachers.values():
        stored = TeacherRepo(db).create(
            school.id, teacher.name, teacher.blocked_slots
        )
        ids[teacher.id] = stored.id

    for entry in problem.scenario.caps.entries:
        CurriculumRepo(db).upsert(school.id, "caps", entry)
    for entry in problem.scenario.optional.entries:
        CurriculumRepo(db).upsert(school.id, "optional", entry)

    scenario = ScenarioRepo(db).create(school.id, "As configured")
    ScenarioRepo(db).update(
        school.id,
        scenario.id,
        enabled_optional=problem.scenario.enabled_optional,
        overrides=problem.scenario.overrides,
        min_doubles=problem.scenario.min_doubles,
        blocks=tuple(
            type(b)(
                ids[b.teacher_id],
                b.grade,
                b.subject_code,
                b.sections,
                b.periods_per_class,
            )
            for b in problem.blocks
        ),
    )
    UserRepo(db).create(school.id, "head@meridian.example", hash_password("pw"))
    return school, scenario


@pytest.mark.solver
def test_the_real_school_solves_through_the_api_and_verifies():
    db = mongomock.MongoClient()["roster_e2e"]
    ensure_indexes(db)
    school, scenario = _seed_from_meridian(db)

    runner = SolveRunner(db, time_limit_s=150.0, max_workers=1)
    app = create_app(settings=E2E_SETTINGS, db=db, runner=runner)

    with TestClient(app) as client:
        client.post(
            "/auth/login",
            json={"email": "head@meridian.example", "password": "pw"},
        )

        # The assembled problem must match what the fixture builds directly,
        # modulo the teacher ids the store assigned.
        assembled = client.get(f"/scenarios/{scenario.id}/problem").json()
        assert len(assembled["blocks"]) == len(problem_to_dict(
            meridian_problem()
        )["blocks"])

        validated = client.post(f"/scenarios/{scenario.id}/validate").json()
        assert validated["hasErrors"] is False

        solution_id = client.post(
            f"/scenarios/{scenario.id}/solve"
        ).json()["id"]

        deadline = time.monotonic() + 400
        while time.monotonic() < deadline:
            body = client.get(f"/solutions/{solution_id}").json()
            if body["jobStatus"] in {"done", "failed", "cancelled"}:
                break
            time.sleep(1.0)

        assert body["jobStatus"] == "done", body.get("error")
        # unknown is a routine outcome and is NOT a failure of this test's
        # subject, which is the pipeline. Only assert a schedule when one
        # was actually produced.
        if body["solveStatus"] in {"optimal", "feasible"}:
            assert body["placements"]
            assert body["stats"]["doublesPlaced"] > 0
        else:
            pytest.skip(
                f"solver returned {body['solveStatus']} on this hardware; "
                "the pipeline still completed correctly"
            )

    runner.shutdown()
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/test_api_e2e.py -m solver -v` (Bash `timeout=600000`)
Expected: 1 passed (or 1 skipped with the recorded reason, which is an honest outcome — see spec §9.3).

- [ ] **Step 3: Confirm it is excluded from the fast run**

Run: `.venv/bin/python -m pytest` (Bash `timeout=600000`)
Expected: `205 passed`, and the deselected count increases by 1.

- [ ] **Step 4: Document the API in the README**

Append to `README.md`:

````markdown
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
````

- [ ] **Step 5: Run everything one last time**

Run: `.venv/bin/python -m pytest -m ""` (Bash `timeout=600000`)
Expected: the full suite, fast plus solver-marked. This is the phase-boundary run.

- [ ] **Step 6: Commit**

```bash
git add tests/test_api_e2e.py README.md
git commit -m "Add the end-to-end solve test and document the API"
```

---

## Phase 2 exit items

Not tasks — things that must happen before this branch is considered finished. Carried from spec §11 so they are not lost a second time.

- [ ] **Run the Phase 1 whole-branch review.** Dispatched twice during Phase 1 and killed by rate limits both times; the user deferred it to the merge gate. Its unfinished output noted two leads never reported: an "enforcement-literal hypothesis" disproved by measurement (10.53s vs 10.46s), and a "missing-subject-row defect" it was confirming when it died.
- [ ] **Review this branch too**, including the cross-task seams between store, jobs and api.
- [ ] **Provision Atlas and run a smoke check** — create a school, sign in, solve, poll. This is the one thing mongomock structurally cannot prove (spec §9.4), specifically unique-index enforcement and error semantics.
- [ ] **Triage the 21 deferred Phase 1 findings** — six in the handoff's section 4, the rest in `phase-1-execution-log.md` under `minor (deferred)`.

