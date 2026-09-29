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


# --- Final review fixes ---------------------------------------------------


@pytest.mark.parametrize("limit", [0, -5, 601])
def test_an_out_of_range_time_limit_is_a_422(solvable, limit):
    client, scenario_id, _ = solvable
    response = client.post(
        f"/scenarios/{scenario_id}/solve", json={"timeLimitS": limit}
    )
    assert response.status_code == 422


def test_the_maximum_time_limit_is_accepted(solvable):
    client, scenario_id, _ = solvable
    response = client.post(
        f"/scenarios/{scenario_id}/solve", json={"timeLimitS": 600}
    )
    assert response.status_code == 202


def test_a_solve_stores_the_canonical_scenario_id(solvable):
    client, scenario_id, _ = solvable
    client.post(f"/scenarios/{scenario_id.upper()}/solve")

    listed = client.get(f"/scenarios/{scenario_id}/solutions").json()
    assert len(listed) == 1


def test_the_history_list_leaves_out_the_heavy_fields(solvable):
    client, scenario_id, _ = solvable
    solution_id = client.post(f"/scenarios/{scenario_id}/solve").json()["id"]

    item = client.get(f"/scenarios/{scenario_id}/solutions").json()[0]
    assert "inputSnapshot" not in item
    assert "placements" not in item
    full = client.get(f"/solutions/{solution_id}").json()
    assert "inputSnapshot" in full and "placements" in full


def test_writing_to_another_school_s_scenario_is_a_404_and_changes_nothing(
    signed_in_client, db
):
    """M14: expected to pass unchanged; the code was already correct."""
    other = SchoolRepo(db).create("Other", (4,), ("A",))
    theirs = ScenarioRepo(db).create(other.id, "Theirs")

    patched = signed_in_client.patch(
        f"/scenarios/{theirs.id}", json={"name": "Renamed"}
    )
    solved = signed_in_client.post(f"/scenarios/{theirs.id}/solve")

    assert patched.status_code == 404
    assert solved.status_code == 404
    assert ScenarioRepo(db).get(other.id, theirs.id).name == "Theirs"
    assert db["solutions"].count_documents({}) == 0
