"""Runs inside the solve child process.

This module imports `roster` core and nothing else — no pymongo, no
fastapi, not even `roster.store`. Three reasons, all load-bearing:

- Atlas M0 caps connections, so a pool of database-connecting children would
  spend them for nothing. The parent performs every write.
- It keeps the pure core pure: the child's import graph is the proof.
- A plain dict in and a plain dict out means nothing crossing the process
  boundary needs a custom pickle.
"""

from __future__ import annotations

from typing import Any

from roster.io import problem_from_dict, result_to_dict
from roster.solve import solve

# Phase 1 defaulted to 30 seconds because a synchronous HTTP request could
# not wait longer. Measured, that default costs 125 of 171 possible doubles
# against 167 at 150 seconds. Behind a polling job the wait costs a user
# nothing but a progress indicator.
DEFAULT_TIME_LIMIT_S = 150.0


def solve_snapshot(
    snapshot: dict[str, Any],
    time_limit_s: float = DEFAULT_TIME_LIMIT_S,
) -> dict[str, Any]:
    """Solve a frozen problem snapshot and return a JSON-safe result."""
    problem = problem_from_dict(snapshot)
    result = solve(problem, time_limit_s=time_limit_s)
    return result_to_dict(result)
