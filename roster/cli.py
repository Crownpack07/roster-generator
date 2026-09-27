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

    problem = problem_from_dict(data)
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
