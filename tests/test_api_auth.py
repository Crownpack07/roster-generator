from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from roster.api.deps import current_session
from roster.api.security import SESSION_COOKIE, hash_password, sign_session
from roster.store.repositories import SchoolRepo, UserRepo

from tests.conftest import TEST_SETTINGS


def _request(cookies: dict[str, str]):
    """The smallest object current_session needs.

    Driving it directly is deliberate: every route-level test of the 401 path
    can be satisfied by a secondary lookup further down the handler, which is
    how this guarantee went untested in the first place.
    """
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=TEST_SETTINGS)),
        cookies=cookies,
    )


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
    """Covers /auth/me's rejection path end to end. The current_session
    guarantee itself is pinned by test_current_session_rejects_a_missing_cookie
    and test_current_session_rejects_a_forged_cookie (direct tests below)."""
    assert client.get("/auth/me").status_code == 401


def test_me_returns_the_signed_in_school(signed_in_client, school):
    response = signed_in_client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["schoolId"] == school.id
    assert response.json()["email"] == "head@meridian.example"


def test_a_forged_cookie_is_rejected(client):
    """Covers /auth/me's rejection path end to end. The current_session
    guarantee itself is pinned by test_current_session_rejects_a_forged_cookie
    (direct test below)."""
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


# Direct tests of current_session, the single entry point for school_id.
# These must discriminate: rejection tests must not pass by rejecting
# everything, and acceptance must not pass by accepting everything.


def test_current_session_rejects_a_missing_cookie():
    """current_session raises 401 when no session cookie is present."""
    with pytest.raises(HTTPException) as caught:
        current_session(_request({}))
    assert caught.value.status_code == 401


def test_current_session_rejects_a_forged_cookie():
    """current_session raises 401 when the session cookie is forged or invalid."""
    with pytest.raises(HTTPException) as caught:
        current_session(_request({SESSION_COOKIE: "forged"}))
    assert caught.value.status_code == 401


def test_current_session_accepts_a_validly_signed_cookie():
    """The positive case, so the two rejections above cannot pass by
    rejecting everything."""
    token = sign_session(TEST_SETTINGS.session_secret, "school-1", "user-1")
    session = current_session(_request({SESSION_COOKIE: token}))
    assert (session.school_id, session.user_id) == ("school-1", "user-1")
