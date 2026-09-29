"""Pydantic models, used only at the HTTP edge.

Domain dataclasses never become Pydantic models: that would drag web
concerns into the pure core. `roster/io.py` is the bridge for anything
solver-shaped, and it already emits camelCase.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class SessionResponse(BaseModel):
    schoolId: str
    userId: str
    email: str
    schoolName: str


class SchoolResponse(BaseModel):
    id: str
    name: str
    cycleDays: int
    periodsPerDay: int
    grades: list[int]
    sections: list[str]


class SchoolUpdate(BaseModel):
    name: str = Field(min_length=1)


class TeacherRequest(BaseModel):
    name: str = Field(min_length=1)
    blockedSlots: list[int] = Field(default_factory=list)


class TeacherUpdate(BaseModel):
    name: str | None = None
    blockedSlots: list[int] | None = None


class TeacherResponse(BaseModel):
    id: str
    name: str
    blockedSlots: list[int]


class SubjectRequest(BaseModel):
    code: str
    displayName: str
    isCore: bool
    isOptional: bool = False


class SubjectUpdate(BaseModel):
    displayName: str | None = None
    isCore: bool | None = None
    isOptional: bool | None = None


class SubjectResponse(BaseModel):
    code: str
    displayName: str
    isCore: bool
    isOptional: bool


class CurriculumRequest(BaseModel):
    kind: str
    grade: int
    subjectCode: str
    periods: int


class CurriculumResponse(BaseModel):
    kind: str
    grade: int
    subjectCode: str
    periods: int


class OverrideValue(BaseModel):
    """Key names match roster/io.py, so the scenario routes and the
    /problem route describe an override with the same words."""

    grade: int
    subject: str
    periods: int


class MinDoubleValue(BaseModel):
    grade: int
    subject: str
    minimum: int


class BlockRequest(BaseModel):
    teacherId: str
    grade: int
    subject: str
    sections: list[str]
    periodsPerClass: int


class ScenarioRequest(BaseModel):
    name: str = Field(min_length=1)


class ScenarioUpdate(BaseModel):
    name: str | None = None
    enabledOptional: list[str] | None = None
    overrides: list[OverrideValue] | None = None
    minDoubles: list[MinDoubleValue] | None = None
    blocks: list[BlockRequest] | None = None


class ScenarioResponse(BaseModel):
    id: str
    name: str
    enabledOptional: list[str]
    overrides: list[OverrideValue]
    minDoubles: list[MinDoubleValue]
    blocks: list[BlockRequest]


class FindingResponse(BaseModel):
    code: str
    severity: str
    message: str


class ValidateResponse(BaseModel):
    findings: list[FindingResponse]
    hasErrors: bool


class SolveRequest(BaseModel):
    timeLimitS: float | None = Field(default=None, gt=0, le=600)
