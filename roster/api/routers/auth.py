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
