"""Drives solves as background jobs.

Two executors, deliberately:

- a single-slot ThreadPoolExecutor orchestrates and performs the MongoDB
  writes. It lives in the parent process, so it may.
- a ProcessPoolExecutor runs CP-SAT, which saturates whatever cores it is
  given and cannot be interrupted once started.

concurrent.futures offers no "task started" callback, so without the thread
the runner could not honestly report `running` — it would have to guess, and
a guessed status is exactly what spec §5.2 forbids.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from enum import StrEnum
from typing import Any

from pymongo.database import Database

from roster.jobs.worker import DEFAULT_TIME_LIMIT_S, solve_snapshot
from roster.store.repositories import SolutionRepo


log = logging.getLogger(__name__)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


def solver_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return f"ortools {version('ortools')}"
    except PackageNotFoundError:
        return "ortools unknown"


class SolveRunner:
    def __init__(
        self,
        db: Database,
        *,
        time_limit_s: float = DEFAULT_TIME_LIMIT_S,
        max_workers: int = 1,
        solve_fn=solve_snapshot,
        thread_pool=None,
        process_pool=None,
    ) -> None:
        self._solutions = SolutionRepo(db)
        self._time_limit_s = time_limit_s
        self._max_workers = max_workers
        self._solve_fn = solve_fn
        self._threads = thread_pool
        self._processes = process_pool
        self._version = solver_version()
        self._pool_lock = threading.Lock()

    def start(self) -> None:
        """Build the pools (if not injected) and sweep orphaned jobs.

        Assumes a SINGLE application process. `sweep_orphans` fails every
        `queued`/`running` job across all tenants on the theory that a
        restart orphans them all alike — true only if this is the one
        process that could have been running them. Running more than one
        process against the same database — for example
        `uvicorn --workers N` with N > 1, or an overlapping rolling deploy —
        breaks that assumption: one process's startup sweep would fail
        another, still-live process's in-flight jobs. Do not run multiple
        worker processes against this runner. The database-level filters on
        `mark_done`/`mark_failed` keep a wrongly-swept job from being
        resurrected into a contradictory document, but the job itself is
        still lost and has to be re-run — deployment configuration is the
        fix, not code.
        """
        if self._threads is None:
            self._threads = ThreadPoolExecutor(
                max_workers=self._max_workers, thread_name_prefix="solve-orchestrator"
            )
        if self._processes is None:
            self._processes = ProcessPoolExecutor(
                max_workers=self._max_workers
            )
        self._solutions.sweep_orphans()

    def shutdown(self) -> None:
        # Do not wait for a running solve (up to its whole time limit), and
        # drop queued work: those rows stay `queued` and the next startup's
        # sweep_orphans marks them failed.
        for pool in (self._threads, self._processes):
            if pool is not None:
                pool.shutdown(wait=False, cancel_futures=True)

    def submit(
        self,
        school_id: str,
        scenario_id: str,
        snapshot: dict[str, Any],
        time_limit_s: float | None = None,
    ) -> str:
        limit = self._time_limit_s if time_limit_s is None else time_limit_s
        solution_id = self._solutions.create_queued(
            school_id, scenario_id, snapshot, limit, self._version
        )
        future = self._threads.submit(
            self._run_job, school_id, solution_id, snapshot, limit
        )
        future.add_done_callback(self._log_failure)
        return solution_id

    @staticmethod
    def _log_failure(future) -> None:
        if future.cancelled():
            return
        exc = future.exception()
        if exc is not None:
            log.error("solve job thread failed", exc_info=exc)

    def _replace_broken_pool(self, broken) -> None:
        """A dead child poisons the whole executor; swap in a fresh one.

        Jobs failing at the same time all arrive here with the same broken
        pool, so only the first replaces it.
        """
        with self._pool_lock:
            if self._processes is broken:
                self._processes = ProcessPoolExecutor(
                    max_workers=self._max_workers
                )
                broken.shutdown(wait=False)

    def cancel(self, school_id: str, solution_id: str) -> bool:
        """Only while queued. A running CP-SAT solve cannot be interrupted.

        It does not need to be: the time limit bounds every solve, so a
        running job finishes on its own.

        This only flips the database row; it does not also try to cancel
        the pending `Future`. `mark_running`'s `jobStatus: "queued"` filter
        is the real guarantee — a job cancelled here simply fails to
        transition when `_run_job` later calls it, regardless of whether
        the thread pool had already picked the task up. A `Future.cancel()`
        call bought nothing correctness could rely on (it only succeeds
        before the pool starts the task, which is not guaranteed) and it
        needed a `_pending` map to reach the `Future`, which leaked: the
        map was populated after `submit()` returned, so a fast `_run_job`
        could finish before the entry was ever recorded, and the early
        return when `mark_running` fails skipped the cleanup that would
        have removed it.
        """
        return self._solutions.cancel_if_queued(school_id, solution_id)

    def _run_job(
        self,
        school_id: str,
        solution_id: str,
        snapshot: dict[str, Any],
        time_limit_s: float,
    ) -> None:
        if not self._solutions.mark_running(school_id, solution_id):
            # Cancelled between submission and execution. Nothing to do.
            return
        pool = self._processes
        try:
            payload = pool.submit(self._solve_fn, snapshot, time_limit_s).result()
        except BaseException as exc:  # noqa: BLE001
            # A crash is `failed`, never `unknown`. "We broke" and "the
            # solver could not decide" are different answers to the user.
            # BaseException because a cancelled pool future raises
            # CancelledError, which must still be recorded as `failed`.
            if isinstance(exc, BrokenProcessPool):
                self._replace_broken_pool(pool)
            self._solutions.mark_failed(
                school_id, solution_id, f"{type(exc).__name__}: {exc}"
            )
            return
        try:
            self._solutions.mark_done(school_id, solution_id, payload)
        except Exception as exc:  # noqa: BLE001
            self._solutions.mark_failed(
                school_id,
                solution_id,
                f"could not record result: {type(exc).__name__}: {exc}",
            )
