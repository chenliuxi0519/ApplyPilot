import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
    get_current_user,
)
from app.modules.programs import service
from app.modules.programs.models import (
    EvidenceStatus,
    Program,
    RequirementFieldName,
    University,
)
from app.modules.programs.schemas import (
    ConflictPublic,
    ConflictsPublic,
    EvidenceCreate,
    EvidenceIngestPublic,
    EvidenceListPublic,
    EvidencePublic,
    EvidenceReview,
    ProgramPublic,
    ProgramSearchFilters,
    ProgramsPublic,
    ProgramWithUniversityPublic,
    RequirementPublic,
    RequirementReviewPublic,
    RequirementsPublic,
    UniversityPublic,
)

router = APIRouter(
    prefix="/programs",
    tags=["programs"],
    dependencies=[Depends(get_current_user)],
)
review_router = APIRouter(
    prefix="/requirements",
    tags=["requirements"],
    dependencies=[Depends(get_current_active_superuser)],
)


@router.get("/", response_model=ProgramsPublic)
def search_programs(
    session: SessionDep,
    filters: Annotated[ProgramSearchFilters, Query()],
) -> Any:
    rows, count = service.search_programs(session=session, filters=filters)
    return ProgramsPublic(
        data=[_program_public(program, university) for program, university in rows],
        count=count,
    )


@router.get("/{program_id}", response_model=ProgramWithUniversityPublic)
def read_program(session: SessionDep, program_id: uuid.UUID) -> Any:
    try:
        program, university = service.get_program_with_university(
            session=session, program_id=program_id
        )
    except service.ProgramNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _program_public(program, university)


@router.get("/{program_id}/requirements", response_model=RequirementsPublic)
def read_program_requirements(
    session: SessionDep,
    program_id: uuid.UUID,
    application_cycle: str | None = None,
) -> Any:
    _get_program(session=session, program_id=program_id)
    requirements = service.list_requirements(
        session=session, program_id=program_id, application_cycle=application_cycle
    )
    return RequirementsPublic(
        data=[RequirementPublic.model_validate(row) for row in requirements],
        count=len(requirements),
    )


@router.get("/{program_id}/evidence", response_model=EvidenceListPublic)
def read_program_evidence(
    session: SessionDep,
    program_id: uuid.UUID,
    application_cycle: str | None = None,
    field_name: RequirementFieldName | None = None,
    status: EvidenceStatus | None = None,
) -> Any:
    _get_program(session=session, program_id=program_id)
    evidence = service.list_evidence(
        session=session,
        program_id=program_id,
        application_cycle=application_cycle,
        field_name=field_name,
        status=status,
    )
    return EvidenceListPublic(
        data=[EvidencePublic.model_validate(row) for row in evidence],
        count=len(evidence),
    )


@router.post(
    "/{program_id}/evidence",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=EvidenceIngestPublic,
)
def ingest_program_evidence(
    *,
    session: SessionDep,
    program_id: uuid.UUID,
    evidence_in: EvidenceCreate,
) -> Any:
    try:
        result = service.ingest_evidence(
            session=session, program_id=program_id, evidence_in=evidence_in
        )
    except (service.ProgramNotFoundError, service.RequirementNotFoundError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except service.ProgramValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return EvidenceIngestPublic(
        outcome=result.outcome.value,
        evidence=EvidencePublic.model_validate(result.evidence),
        requirement=RequirementPublic.model_validate(result.requirement),
    )


@review_router.get("/conflicts", response_model=ConflictsPublic)
def read_requirement_conflicts(
    session: SessionDep,
    program_id: uuid.UUID | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    conflicts, count = service.list_conflicts(
        session=session, program_id=program_id, skip=skip, limit=limit
    )
    return ConflictsPublic(
        data=[
            ConflictPublic(
                requirement=RequirementPublic.model_validate(conflict.requirement),
                conflicting_evidence=[
                    EvidencePublic.model_validate(row)
                    for row in conflict.conflicting_evidence
                ],
            )
            for conflict in conflicts
        ],
        count=count,
    )


@review_router.post(
    "/evidence/{evidence_id}/accept", response_model=RequirementReviewPublic
)
def accept_requirement_evidence(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    evidence_id: uuid.UUID,
    review_in: EvidenceReview | None = None,
) -> Any:
    return _review(
        action=service.accept_evidence,
        session=session,
        reviewer_id=current_user.id,
        evidence_id=evidence_id,
        review_in=review_in,
    )


@review_router.post(
    "/evidence/{evidence_id}/reject", response_model=RequirementReviewPublic
)
def reject_requirement_evidence(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    evidence_id: uuid.UUID,
    review_in: EvidenceReview | None = None,
) -> Any:
    return _review(
        action=service.reject_evidence,
        session=session,
        reviewer_id=current_user.id,
        evidence_id=evidence_id,
        review_in=review_in,
    )


def _review(
    *,
    action: Callable[..., service.RequirementReviewResult],
    session: Session,
    reviewer_id: uuid.UUID,
    evidence_id: uuid.UUID,
    review_in: EvidenceReview | None,
) -> RequirementReviewPublic:
    try:
        result = action(
            session=session,
            evidence_id=evidence_id,
            reviewer_id=reviewer_id,
            note=None if review_in is None else review_in.note,
        )
    except (
        service.EvidenceNotFoundError,
        service.RequirementNotFoundError,
        service.ProgramNotFoundError,
    ) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except service.EvidenceStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return RequirementReviewPublic(
        decision=result.decision,
        evidence=EvidencePublic.model_validate(result.evidence),
        requirement=RequirementPublic.model_validate(result.requirement),
    )


def _get_program(*, session: Session, program_id: uuid.UUID) -> Program:
    try:
        return service.get_program_or_raise(session=session, program_id=program_id)
    except service.ProgramNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _program_public(
    program: Program, university: University
) -> ProgramWithUniversityPublic:
    return ProgramWithUniversityPublic(
        **ProgramPublic.model_validate(program).model_dump(),
        university=UniversityPublic.model_validate(university),
    )
