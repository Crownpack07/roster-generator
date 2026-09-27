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
    solve_cmd.add_argument("--workers", type=int, default=None)

    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    raise SystemExit(main())
