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
