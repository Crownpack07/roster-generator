"""School, teachers, subjects and curriculum.

Every handler is `def`, not `async def`, so FastAPI runs it in a threadpool
and the synchronous MongoDB driver never blocks the event loop.

A document outside the session's school produces 404, never 403: a 403 would
confirm that the id exists, which is itself a leak across tenants.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pymongo.errors import DuplicateKeyError

from roster.api.deps import Session, current_session, get_db
from roster.api.schemas import (
    CurriculumRequest,
    CurriculumResponse,
    SchoolResponse,
    SchoolUpdate,
    SubjectRequest,
    SubjectResponse,
    SubjectUpdate,
    TeacherRequest,
    TeacherResponse,
    TeacherUpdate,
)
from roster.curriculum import CurriculumEntry
from roster.domain import SLOT_COUNT, Subject
from roster.store.repositories import (
    CurriculumRepo,
    SchoolRepo,
    SubjectRepo,
    TeacherRepo,
)

router = APIRouter(tags=["entities"])

_KINDS = {"caps", "optional"}


def _teacher_response(teacher) -> TeacherResponse:
    return TeacherResponse(
        id=teacher.id,
        name=teacher.name,
        blockedSlots=sorted(teacher.blocked_slots),
    )


def _checked_slots(slots: list[int]) -> frozenset[int]:
    for slot in slots:
        if not 0 <= slot < SLOT_COUNT:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"blocked slot {slot} is outside the cycle "
                    f"(0..{SLOT_COUNT - 1})"
                ),
            )
    return frozenset(slots)


def _checked_kind(kind: str) -> str:
    if kind not in _KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of {sorted(_KINDS)}, got {kind!r}",
        )
    return kind


@router.get("/school", response_model=SchoolResponse)
def read_school(
    session: Session = Depends(current_session), db=Depends(get_db)
) -> SchoolResponse:
    school = SchoolRepo(db).get(session.school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="school not found")
    return SchoolResponse(
        id=school.id,
        name=school.name,
        cycleDays=school.cycle_days,
        periodsPerDay=school.periods_per_day,
        grades=list(school.grades),
        sections=list(school.sections),
    )


@router.patch("/school", response_model=SchoolResponse)
def update_school(
    payload: SchoolUpdate,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> SchoolResponse:
    school = SchoolRepo(db).update(session.school_id, name=payload.name)
    if school is None:
        raise HTTPException(status_code=404, detail="school not found")
    return read_school(session=session, db=db)


@router.get("/teachers", response_model=list[TeacherResponse])
def list_teachers(
    session: Session = Depends(current_session), db=Depends(get_db)
) -> list[TeacherResponse]:
    return [_teacher_response(t) for t in TeacherRepo(db).list(session.school_id)]


@router.post("/teachers", response_model=TeacherResponse, status_code=201)
def create_teacher(
    payload: TeacherRequest,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> TeacherResponse:
    teacher = TeacherRepo(db).create(
        session.school_id, payload.name, _checked_slots(payload.blockedSlots)
    )
    return _teacher_response(teacher)


@router.get("/teachers/{teacher_id}", response_model=TeacherResponse)
def read_teacher(
    teacher_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> TeacherResponse:
    teacher = TeacherRepo(db).get(session.school_id, teacher_id)
    if teacher is None:
        raise HTTPException(status_code=404, detail="teacher not found")
    return _teacher_response(teacher)


@router.patch("/teachers/{teacher_id}", response_model=TeacherResponse)
def update_teacher(
    teacher_id: str,
    payload: TeacherUpdate,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> TeacherResponse:
    slots = (
        None
        if payload.blockedSlots is None
        else _checked_slots(payload.blockedSlots)
    )
    teacher = TeacherRepo(db).update(
        session.school_id, teacher_id, name=payload.name, blocked_slots=slots
    )
    if teacher is None:
        raise HTTPException(status_code=404, detail="teacher not found")
    return _teacher_response(teacher)


@router.delete("/teachers/{teacher_id}", status_code=204)
def delete_teacher(
    teacher_id: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> Response:
    if not TeacherRepo(db).delete(session.school_id, teacher_id):
        raise HTTPException(status_code=404, detail="teacher not found")
    return Response(status_code=204)


@router.get("/subjects", response_model=list[SubjectResponse])
def list_subjects(
    session: Session = Depends(current_session), db=Depends(get_db)
) -> list[SubjectResponse]:
    return [
        SubjectResponse(
            code=s.code,
            displayName=s.display_name,
            isCore=s.is_core,
            isOptional=s.is_optional,
        )
        for s in SubjectRepo(db).list(session.school_id)
    ]


@router.post("/subjects", response_model=SubjectResponse, status_code=201)
def create_subject(
    payload: SubjectRequest,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> SubjectResponse:
    subject = Subject(
        payload.code, payload.displayName, payload.isCore, payload.isOptional
    )
    try:
        SubjectRepo(db).create(session.school_id, subject)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail=f"subject {payload.code} already exists in this school",
        ) from None
    return SubjectResponse(
        code=subject.code,
        displayName=subject.display_name,
        isCore=subject.is_core,
        isOptional=subject.is_optional,
    )


@router.get("/subjects/{code}", response_model=SubjectResponse)
def read_subject(
    code: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> SubjectResponse:
    subject = SubjectRepo(db).get(session.school_id, code)
    if subject is None:
        raise HTTPException(status_code=404, detail="subject not found")
    return SubjectResponse(
        code=subject.code,
        displayName=subject.display_name,
        isCore=subject.is_core,
        isOptional=subject.is_optional,
    )


@router.patch("/subjects/{code}", response_model=SubjectResponse)
def update_subject(
    code: str,
    payload: SubjectUpdate,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> SubjectResponse:
    subject = SubjectRepo(db).update(
        session.school_id,
        code,
        display_name=payload.displayName,
        is_core=payload.isCore,
        is_optional=payload.isOptional,
    )
    if subject is None:
        raise HTTPException(status_code=404, detail="subject not found")
    return SubjectResponse(
        code=subject.code,
        displayName=subject.display_name,
        isCore=subject.is_core,
        isOptional=subject.is_optional,
    )


@router.delete("/subjects/{code}", status_code=204)
def delete_subject(
    code: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> Response:
    if not SubjectRepo(db).delete(session.school_id, code):
        raise HTTPException(status_code=404, detail="subject not found")
    return Response(status_code=204)


@router.get("/curriculum", response_model=list[CurriculumResponse])
def list_curriculum(
    kind: str = Query("caps"),
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> list[CurriculumResponse]:
    checked = _checked_kind(kind)
    return [
        CurriculumResponse(
            kind=checked,
            grade=e.grade,
            subjectCode=e.subject_code,
            periods=e.periods_per_class,
        )
        for e in CurriculumRepo(db).list(session.school_id, checked)
    ]


@router.put("/curriculum", response_model=CurriculumResponse)
def upsert_curriculum(
    payload: CurriculumRequest,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> CurriculumResponse:
    kind = _checked_kind(payload.kind)
    entry = CurriculumEntry(payload.grade, payload.subjectCode, payload.periods)
    CurriculumRepo(db).upsert(session.school_id, kind, entry)
    return CurriculumResponse(
        kind=kind,
        grade=entry.grade,
        subjectCode=entry.subject_code,
        periods=entry.periods_per_class,
    )


@router.delete("/curriculum/{kind}/{grade}/{subject_code}", status_code=204)
def delete_curriculum(
    kind: str,
    grade: int,
    subject_code: str,
    session: Session = Depends(current_session),
    db=Depends(get_db),
) -> Response:
    checked = _checked_kind(kind)
    if not CurriculumRepo(db).delete(
        session.school_id, checked, grade, subject_code
    ):
        raise HTTPException(status_code=404, detail="curriculum entry not found")
    return Response(status_code=204)
