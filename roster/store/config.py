"""Settings read from the environment.

Required values have no defaults. A default that happens to work in
development is worse than a refusal to start, because it fails silently in
production.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(Exception):
    """A required setting is missing or malformed."""


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str
    session_secret: str
    mongodb_db: str = "roster"
    solve_time_limit_s: float = 150.0
    solve_max_workers: int = 1
    cookie_secure: bool = True


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required and has no default")
    return value


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def settings_from_env(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    return Settings(
        mongodb_uri=_required(env, "MONGODB_URI"),
        session_secret=_required(env, "SESSION_SECRET"),
        mongodb_db=env.get("MONGODB_DB", "").strip() or "roster",
        solve_time_limit_s=_float(env, "SOLVE_TIME_LIMIT_S", 150.0),
        solve_max_workers=_int(env, "SOLVE_MAX_WORKERS", 1),
        cookie_secure=_bool(env, "COOKIE_SECURE", True),
    )
