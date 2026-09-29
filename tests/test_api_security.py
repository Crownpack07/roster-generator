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
    head, sig = token.rsplit(".", 1)
    tampered = f"{head}.{'A' if sig[0] != 'A' else 'B'}{sig[1:]}"
    assert read_session(SECRET, tampered) is None

    other_head = sign_session(SECRET, "school-2", "user-2").rsplit(".", 1)[0]
    assert read_session(SECRET, f"{other_head}.{sig}") is None


def test_an_expired_token_is_rejected():
    token = sign_session(SECRET, "school-1", "user-1")
    assert read_session(SECRET, token, max_age_s=-1) is None


def test_a_token_that_is_not_a_token_at_all_is_rejected():
    assert read_session(SECRET, "") is None
    assert read_session(SECRET, "garbage") is None
