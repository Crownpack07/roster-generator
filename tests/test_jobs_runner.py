import pytest

from roster.jobs.runner import JobStatus, SolveRunner
from roster.store.repositories import SolutionRepo

from tests.conftest import DeferredExecutor, InlineExecutor

SNAPSHOT = {"grades": [4], "sections": ["A"]}  # opaque to the runner

DONE_PAYLOAD = {
    "status": "feasible",
    "doublesPlaced": 12,
    "doublesCeiling": 20,
    "wallSeconds": 1.5,
    "findings": [],
    "conflict": None,
    "placements": [
        {"grade": 4, "section": "A", "subject": "MAT", "slot": 0}
    ],
}


def make_runner(db, solve_fn=None, thread_pool=None, process_pool=None):
    runner = SolveRunner(
        db,
        solve_fn=solve_fn or (lambda snapshot, limit: DONE_PAYLOAD),
        thread_pool=thread_pool or InlineExecutor(),
        process_pool=process_pool or InlineExecutor(),
    )
    runner.start()
    return runner


def test_a_submitted_job_reaches_done_and_records_the_solve_status(db):
    runner = make_runner(db)
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    doc = SolutionRepo(db).get("school-1", solution_id)
    assert doc["jobStatus"] == JobStatus.DONE
    assert doc["solveStatus"] == "feasible"
    assert doc["stats"]["doublesPlaced"] == 12
    assert len(doc["placements"]) == 1
    assert doc["finishedAt"] is not None


def test_a_queued_job_has_no_solve_status_yet(db):
    """Review Focus: a client must never read a pending job as 'no answer'."""
    threads = DeferredExecutor()
    runner = make_runner(db, thread_pool=threads)
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    doc = SolutionRepo(db).get("school-1", solution_id)
    assert doc["jobStatus"] == JobStatus.QUEUED
    assert doc["solveStatus"] is None

    threads.run_next()
    assert SolutionRepo(db).get("school-1", solution_id)["jobStatus"] == (
        JobStatus.DONE
    )


def test_the_job_is_marked_running_while_the_solver_works(db):
    """Observed from inside the solve, which is the only honest vantage."""
    seen: list[str] = []

    def watching_solve(snapshot, limit):
        doc = SolutionRepo(db).get("school-1", seen_id[0])
        seen.append(doc["jobStatus"])
        assert doc["solveStatus"] is None
        return DONE_PAYLOAD

    seen_id: list[str] = []
    runner = SolveRunner(
        db,
        solve_fn=watching_solve,
        thread_pool=DeferredExecutor(),
        process_pool=InlineExecutor(),
    )
    runner.start()
    seen_id.append(runner.submit("school-1", "scenario-1", SNAPSHOT))
    runner._threads.run_next()

    assert seen == [JobStatus.RUNNING]


def test_a_crashing_solve_is_failed_and_never_unknown(db):
    """The cardinal rule, one layer up from P1 §7.3.

    'We broke' and 'the solver could not decide' are different answers. A
    crash reported as `unknown` would tell a user their timetable might be
    impossible when in fact nothing was ever attempted.
    """

    def exploding_solve(snapshot, limit):
        raise RuntimeError("ortools went missing")

    runner = make_runner(db, solve_fn=exploding_solve)
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    doc = SolutionRepo(db).get("school-1", solution_id)
    assert doc["jobStatus"] == JobStatus.FAILED
    assert doc["solveStatus"] is None
    assert "ortools went missing" in doc["error"]


def test_an_unknown_solve_result_is_done_not_failed(db):
    """The mirror of the test above: a timeout is a real, finished answer."""
    unknown = {**DONE_PAYLOAD, "status": "unknown", "placements": []}
    runner = make_runner(db, solve_fn=lambda s, limit: unknown)
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    doc = SolutionRepo(db).get("school-1", solution_id)
    assert doc["jobStatus"] == JobStatus.DONE
    assert doc["solveStatus"] == "unknown"


def test_the_snapshot_and_time_limit_are_frozen_on_the_document(db):
    runner = make_runner(db)
    solution_id = runner.submit(
        "school-1", "scenario-1", SNAPSHOT, time_limit_s=42.0
    )

    doc = SolutionRepo(db).get("school-1", solution_id)
    assert doc["inputSnapshot"] == SNAPSHOT
    assert doc["timeLimitS"] == 42.0


def test_a_queued_job_can_be_cancelled_and_then_never_runs(db):
    """Exercises the runner's cancel path, not the database-level guard.

    SolveRunner.cancel also cancels the pending Future, so with a
    DeferredExecutor the task never starts and mark_running is never called
    here. The database guard itself — the actual race protection when the
    pool has already picked the job up — is pinned separately by
    test_mark_running_refuses_a_job_that_is_no_longer_queued below.
    """
    threads = DeferredExecutor()
    calls: list[int] = []
    runner = make_runner(
        db,
        solve_fn=lambda s, limit: calls.append(1) or DONE_PAYLOAD,
        thread_pool=threads,
    )
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    assert runner.cancel("school-1", solution_id) is True
    threads.run_next()  # the thread still fires; the job must decline to run

    doc = SolutionRepo(db).get("school-1", solution_id)
    assert doc["jobStatus"] == JobStatus.CANCELLED
    assert calls == []


def test_a_finished_job_cannot_be_cancelled(db):
    runner = make_runner(db)
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    assert runner.cancel("school-1", solution_id) is False
    assert SolutionRepo(db).get("school-1", solution_id)["jobStatus"] == (
        JobStatus.DONE
    )


def test_a_job_belonging_to_another_school_is_invisible(db):
    runner = make_runner(db)
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    assert SolutionRepo(db).get("school-2", solution_id) is None
    assert runner.cancel("school-2", solution_id) is False


def test_startup_fails_every_job_orphaned_by_a_restart(db):
    """The pool dies with the container, so queued and running are orphans."""
    threads = DeferredExecutor()
    runner = make_runner(db, thread_pool=threads)
    solution_id = runner.submit("school-1", "scenario-1", SNAPSHOT)

    # A second runner is a second process lifetime.
    make_runner(db)

    doc = SolutionRepo(db).get("school-1", solution_id)
    assert doc["jobStatus"] == JobStatus.FAILED
    assert "restarted" in doc["error"]


def test_solutions_are_listed_only_for_their_own_scenario(db):
    runner = make_runner(db)
    first = runner.submit("school-1", "scenario-1", SNAPSHOT)
    second = runner.submit("school-1", "scenario-1", SNAPSHOT)
    runner.submit("school-1", "scenario-2", SNAPSHOT)

    ids = [
        d["id"]
        for d in SolutionRepo(db).list_for_scenario("school-1", "scenario-1")
    ]
    assert set(ids) == {first, second}


def test_mark_running_refuses_a_job_that_is_no_longer_queued(db):
    """The queued filter is the whole cancellation race guarantee.

    The runner-level cancellation test cannot reach this: SolveRunner.cancel
    also cancels the pending Future, so _run_job is never entered and
    mark_running is never called. This drives the database guard directly,
    which is what protects the real race — the pool has already picked the
    job up by the time the cancel arrives.
    """
    repo = SolutionRepo(db)
    solution_id = repo.create_queued(
        "school-1", "scenario-1", {"grades": [4]}, 1.0
    )

    assert repo.cancel_if_queued("school-1", solution_id) is True
    # The pool picks it up regardless; it must decline to start.
    assert repo.mark_running("school-1", solution_id) is False
    assert repo.get("school-1", solution_id)["jobStatus"] == JobStatus.CANCELLED
