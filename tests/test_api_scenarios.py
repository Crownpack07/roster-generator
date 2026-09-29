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


def test_a_valid_scenario_validates_cleanly(seeded_client):
    """The seeded scenario trips nothing: grades 5-7 demand only filler,
    which the coverage checks exclude."""
    client, scenario_id, _ = seeded_client

    response = client.post(f"/scenarios/{scenario_id}/validate")

    assert response.status_code == 200
    assert response.json() == {"findings": [], "hasErrors": False}


def test_validate_returns_findings_with_a_200(seeded_client):
    """A finding is an answer, not an error — 200 even when a check fails.

    This is the contract the Phase 3 assignment editor depends on: it posts
    on every keystroke and renders whatever comes back.
    """
    client, scenario_id, teacher_id = seeded_client
    # A core subject with 5 periods cannot appear on all six days.
    client.put(
        "/curriculum",
        json={"kind": "caps", "grade": 4, "subjectCode": "MAT", "periods": 5},
    )
    # Update the block's periodsPerClass to match the new curriculum.
    client.patch(
        f"/scenarios/{scenario_id}",
        json={
            "blocks": [
                {
                    "teacherId": teacher_id,
                    "grade": 4,
                    "subject": "MAT",
                    "sections": ["A", "B", "C"],
                    "periodsPerClass": 5,
                }
            ]
        },
    )

    response = client.post(f"/scenarios/{scenario_id}/validate")

    assert response.status_code == 200
    body = response.json()
    assert body["hasErrors"] is True
    assert body["findings"], "expected at least one finding"
    assert all(
        {"code", "severity", "message"} <= set(f) for f in body["findings"]
    )
    assert any(f["code"] == "curriculum_bounds" for f in body["findings"])


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
