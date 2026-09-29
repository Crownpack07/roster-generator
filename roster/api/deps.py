"""Request-scoped dependencies.

`current_session` is the single place a schoolId enters the application. No
route reads a schoolId from a path, a query string or a body, so no route can
be talked into another school's data.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request
from pymongo.database import Database

from roster.api.security import SESSION_COOKIE, read_session
from roster.store.config import Settings


@dataclass(frozen=True)
class Session:
    school_id: str
    user_id: str


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_runner(request: Request):
    return request.app.state.runner


def current_session(request: Request) -> Session:
    settings: Settings = request.app.state.settings
    token = request.cookies.get(SESSION_COOKIE, "")
    pair = read_session(settings.session_secret, token)
    if pair is None:
        raise HTTPException(status_code=401, detail="not signed in")
    return Session(school_id=pair[0], user_id=pair[1])
