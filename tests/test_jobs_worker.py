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
