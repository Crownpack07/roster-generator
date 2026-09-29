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
