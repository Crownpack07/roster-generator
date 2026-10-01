"""Command line entry point: python -m roster.cli solve problem.json"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from roster.io import problem_from_dict, result_to_dict
from roster.solve import SolveStatus, solve

_SUCCESS = (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="roster")
    sub = parser.add_subparsers(dest="command", required=True)

    solve_cmd = sub.add_parser("solve", help="solve a problem file")
    solve_cmd.add_argument("path", help="path to a problem JSON file")
    solve_cmd.add_argument("--time-limit", type=float, default=30.0)
    solve_cmd.add_argument("--seed", type=int, default=None)
    solve_cmd.add_argument(
        "--workers",
        type=int,
        default=None,
        help="search threads; default: available cores, at most 16; "
        "never fewer than 4",
    )

    create_cmd = sub.add_parser(
        "create-school", help="create the first school and its login"
    )
    create_cmd.add_argument("--name", required=True)
    create_cmd.add_argument("--email", required=True)
    create_cmd.add_argument("--password", required=True)
    create_cmd.add_argument("--grades", default="4,5,6,7")
    create_cmd.add_argument("--sections", default="A,B,C")

    args = parser.parse_args(argv)

    if args.command == "create-school":
        return _create_school(args)

    path = Path(args.path)
    if not path.is_file():
        print(f"error: {path} not found", file=sys.stderr)
        return 2

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: {path} is not valid JSON ({exc})", file=sys.stderr)
        return 2

    try:
        problem = problem_from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        # Valid JSON, wrong shape: a missing or misspelled key, a truncated
        # write, an older schema. problem_from_dict indexes directly, so this
        # would otherwise surface as an uncaught KeyError — a traceback and
        # exit 1, where the contract says exit 2 with a message.
        print(
            f"error: {path} is not a valid problem file ({exc!r})",
            file=sys.stderr,
        )
        return 2

    result = solve(
        problem,
        time_limit_s=args.time_limit,
        seed=args.seed,
        workers=args.workers,
    )
    print(json.dumps(result_to_dict(result), indent=2))
    return 0 if result.status in _SUCCESS else 1


def _database_for_cli(settings):
    """Split out so tests can substitute an in-memory database.

    The pymongo imports live inside this function, not at module top level:
    `roster.cli solve` must keep working for anyone who installed the
    package without the `server` extra.
    """
    from roster.store.client import get_database, make_client

    return get_database(make_client(settings), settings)


def _create_school(args) -> int:
    from pymongo.errors import DuplicateKeyError, PyMongoError

    from roster.api.security import hash_password
    from roster.store.config import ConfigError, settings_from_env
    from roster.store.indexes import ensure_indexes
    from roster.store.repositories import (
        SchoolRepo,
        UserRepo,
        ValidationError,
    )

    try:
        settings = settings_from_env()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Parse grades/sections before connecting to database (Ruling 23)
    try:
        grades = tuple(
            int(g) for g in args.grades.split(",") if g.strip()
        )
        sections = tuple(s.strip() for s in args.sections.split(",") if s.strip())
    except ValueError:
        print(f"error: --grades must be integers, got {args.grades!r}", file=sys.stderr)
        return 2

    email = args.email.strip().lower()

    try:
        db = _database_for_cli(settings)
        ensure_indexes(db)

        # Ruling 21: check email BEFORE creating school to avoid orphans
        if UserRepo(db).by_email(email) is not None:
            print(
                f"error: {email} already has an account",
                file=sys.stderr,
            )
            return 2

        try:
            school = SchoolRepo(db).create(args.name, grades, sections)
        except ValidationError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        try:
            UserRepo(db).create(
                school.id, email, hash_password(args.password)
            )
        except DuplicateKeyError:
            print(
                f"error: {email} already has an account",
                file=sys.stderr,
            )
            return 2

        print(f"created school {school.name} ({school.id}) with login {email}")
        return 0
    except PyMongoError as exc:
        # Ruling 23: catch database connection/operation errors (not DuplicateKeyError)
        print(f"error: could not reach the database: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
