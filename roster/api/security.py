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
