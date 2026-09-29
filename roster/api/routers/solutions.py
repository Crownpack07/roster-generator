"""Enqueue a solve, poll it, list history, cancel while queued.

The response carries `jobStatus` and `solveStatus` as separate fields and
never merges them. A crashed job is `failed` with `solveStatus: null`; a
solve that exhausted its clock is `done` with `solveStatus: "unknown"`. The
UI is required to keep them apart (P1 §7.3), so the API must hand them over
apart.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from roster.api.deps import Session, current_session, get_db, get_runner
from roster.api.routers.scenarios import assemble_or_http
from roster.api.schemas import SolveRequest
from roster.io import problem_to_dict
from roster.store.repositories import SolutionRepo

router = APIRouter(tags=["solutions"])


@router.post("/scenarios/{scenario_id}/solve", status_code=202)
def start_solve(
    scenario_id: str,
    payload: SolveRequest | None = None,
    session: Session = Depends(current_session),
    db=Depends(get_db),
    runner=Depends(get_runner),
) -> dict[str, str]:
    """Freeze the input and hand it to the job runner.

    The snapshot is taken now, not when the job starts, so edits made while
    the job waits in the queue cannot change what is solved.
    """
    problem = assemble_or_http(db, session.school_id, scenario_id)
    time_limit = payload.timeLimitS if payload is not None else None
    solution_id = runner.submit(
        session.school_id,
        scenario_id,
        problem_to_dict(problem),
        time_limit_s=time_limit,
    )
    return {"id": solution_id}


@router.get("/scenarios/{scenario_id}/solutions")
def list_solutions(
    scenario_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> list[dict]:
    return SolutionRepo(db).list_for_scenario(session.school_id, scenario_id)


@router.get("/solutions/{solution_id}")
def read_solution(
    solution_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> dict:
    doc = SolutionRepo(db).get(session.school_id, solution_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="solution not found")
    return doc


@router.post("/solutions/{solution_id}/cancel")
def cancel_solve(
    solution_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
    runner=Depends(get_runner),
) -> dict[str, bool]:
    doc = SolutionRepo(db).get(session.school_id, solution_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="solution not found")
    if not runner.cancel(session.school_id, solution_id):
        # A running CP-SAT solve cannot be interrupted without killing the
        # pool process. The time limit bounds it, so it will finish shortly.
        raise HTTPException(
            status_code=409,
            detail=(
                f"solution is {doc['jobStatus']}; only a queued solve can be "
                "cancelled"
            ),
        )
    return {"cancelled": True}
