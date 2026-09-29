import pytest

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
        response = getattr(client, method)(path)
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


def test_every_route_that_needs_a_session_rejects_a_request_without_one(client):
    """Derived from app.routes, so a route added later is covered for free.

    Task 9's hand-written version probed 5 of 15 paths. A list of paths goes
    stale the moment someone adds a route; the app object never does.
    """
    public = {"/auth/login", "/auth/logout", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    checked = 0

    def collect_routes(app_obj, prefix=""):
        """Recursively collect routes from app and included routers."""
        routes = []
        for route in app_obj.routes:
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            # Handle included routers
            if path is None and hasattr(route, "original_router"):
                nested = collect_routes(route.original_router, prefix)
                routes.extend(nested)
            elif path:
                routes.append((prefix + path, methods, route))
        return routes

    all_routes = collect_routes(client.app)
    for path, methods, route in all_routes:
        if not path or not methods or path in public:
            continue
        # Substitute any path parameter with a syntactically valid value.
        concrete = path
        for name in getattr(route, "param_convertors", {}) or {}:
            concrete = concrete.replace("{" + name + "}", "1")
        if "{" in concrete:
            continue  # unsubstituted parameter; skip rather than guess
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            response = client.request(method, concrete, json={})
            assert response.status_code == 401, (
                f"{method} {concrete} returned {response.status_code}, "
                "not 401, without a session"
            )
            checked += 1

    # Guards against the sweep silently checking nothing.
    assert checked >= 15, f"only swept {checked} routes"


# --- Final review fixes ---------------------------------------------------


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/teachers", {"name": ""}),
        ("patch", "/school", {"name": ""}),
        ("post", "/scenarios", {"name": ""}),
    ],
)
def test_an_empty_name_is_a_422(signed_in_client, method, path, body):
    response = getattr(signed_in_client, method)(path, json=body)
    assert response.status_code == 422


def test_teachers_with_the_same_name_list_in_insertion_order(db):
    from roster.store.repositories import TeacherRepo

    repo = TeacherRepo(db)
    ids = [repo.create("s", "Karin", frozenset()).id for _ in range(5)]
    assert [t.id for t in repo.list("s")] == ids
