"""Scenarios, assembly and pre-flight validation.

`GET /scenarios/{id}/problem` returns the assembled Problem in roster.io's
format. Assembly happens here and in the solve job through the SAME function,
so the problem the UI reasons about and the one the solver receives cannot
diverge. P1 §8 makes that argument about validation; assembly is the same
trap one layer down.

A missing scenario is 404. A scenario that exists but cannot be assembled —
a block naming a deleted teacher, say — is 422: the request was well formed
and the stored data is not.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from roster.api.deps import Session, current_session, get_db
from roster.api.schemas import (
    BlockRequest,
    FindingResponse,
    MinDoubleValue,
    OverrideValue,
    ScenarioRequest,
    ScenarioResponse,
    ScenarioUpdate,
    ValidateResponse,
)
from roster.domain import Block
from roster.io import problem_to_dict
from roster.preflight import has_errors, preflight
from roster.store.assemble import AssemblyError, assemble_problem
from roster.store.repositories import ScenarioRepo

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def _response(record) -> ScenarioResponse:
    return ScenarioResponse(
        id=record.id,
        name=record.name,
        enabledOptional=sorted(record.enabled_optional),
        overrides=[
            OverrideValue(grade=g, subject=c, periods=v)
            for (g, c), v in sorted(record.overrides.items())
        ],
        minDoubles=[
            MinDoubleValue(grade=g, subject=c, minimum=v)
            for (g, c), v in sorted(record.min_doubles.items())
        ],
        blocks=[
            BlockRequest(
                teacherId=b.teacher_id,
                grade=b.grade,
                subject=b.subject_code,
                sections=list(b.sections),
                periodsPerClass=b.periods_per_class,
            )
            for b in record.blocks
        ],
    )


def _overrides(
    rows: list[OverrideValue] | None,
) -> dict[tuple[int, str], int] | None:
    if rows is None:
        return None
    return {(r.grade, r.subject): r.periods for r in rows}


def _min_doubles(
    rows: list[MinDoubleValue] | None,
) -> dict[tuple[int, str], int] | None:
    if rows is None:
        return None
    return {(r.grade, r.subject): r.minimum for r in rows}


def assemble_or_http(db, school_id: str, scenario_id: str):
    """Shared by the problem, validate and solve routes.

    Kept here rather than duplicated so all three translate the same failure
    the same way.
    """
    if ScenarioRepo(db).get(school_id, scenario_id) is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    try:
        return assemble_problem(db, school_id, scenario_id)
    except AssemblyError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from None


@router.get("", response_model=list[ScenarioResponse])
def list_scenarios(
    session: Session = Depends(current_session), db=Depends(get_db)
) -> list[ScenarioResponse]:
    return [_response(r) for r in ScenarioRepo(db).list(session.school_id)]


@router.post("", response_model=ScenarioResponse, status_code=201)
def create_scenario(
    payload: ScenarioRequest,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> ScenarioResponse:
    return _response(ScenarioRepo(db).create(session.school_id, payload.name))


@router.get("/{scenario_id}", response_model=ScenarioResponse)
def read_scenario(
    scenario_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> ScenarioResponse:
    record = ScenarioRepo(db).get(session.school_id, scenario_id)
    if record is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    return _response(record)


@router.patch("/{scenario_id}", response_model=ScenarioResponse)
def update_scenario(
    scenario_id: str,
    payload: ScenarioUpdate,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> ScenarioResponse:
    blocks = (
        None
        if payload.blocks is None
        else tuple(
            Block(
                b.teacherId,
                b.grade,
                b.subject,
                tuple(b.sections),
                b.periodsPerClass,
            )
            for b in payload.blocks
        )
    )
    enabled = (
        None
        if payload.enabledOptional is None
        else frozenset(payload.enabledOptional)
    )
    try:
        record = ScenarioRepo(db).update(
            session.school_id,
            scenario_id,
            name=payload.name,
            enabled_optional=enabled,
            overrides=_overrides(payload.overrides),
            min_doubles=_min_doubles(payload.minDoubles),
            blocks=blocks,
        )
    except ValueError as exc:
        # Block.__post_init__ rejects an empty or duplicated section list.
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if record is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    return _response(record)


@router.delete("/{scenario_id}", status_code=204)
def delete_scenario(
    scenario_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> Response:
    if not ScenarioRepo(db).delete(session.school_id, scenario_id):
        raise HTTPException(status_code=404, detail="scenario not found")
    return Response(status_code=204)


@router.get("/{scenario_id}/problem")
def read_problem(
    scenario_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> dict:
    problem = assemble_or_http(db, session.school_id, scenario_id)
    return problem_to_dict(problem)


@router.post("/{scenario_id}/validate", response_model=ValidateResponse)
def validate_scenario(
    scenario_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> ValidateResponse:
    """Arithmetic pre-flight only — never the solver.

    This is where the assignment editor's live feedback comes from, so it
    must stay in the milliseconds. A finding is an answer, not an error, so
    the status is 200 even when every check fails.
    """
    problem = assemble_or_http(db, session.school_id, scenario_id)
    findings = preflight(problem)
    return ValidateResponse(
        findings=[
            FindingResponse(code=f.code, severity=f.severity, message=f.message)
            for f in findings
        ],
        hasErrors=has_errors(findings),
    )
