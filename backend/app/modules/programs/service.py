import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import ARRAY, ColumnElement, String, func, or_
from sqlalchemy import cast as sa_cast
from sqlmodel import Session, col, select

from app.modules.columns import get_datetime_utc
from app.modules.programs.models import (
    EvidenceStatus,
    Program,
    ProgramRequirement,
    RequirementEvidence,
    RequirementFieldName,
    RequirementReviewLog,
    RequirementStatus,
    ReviewDecision,
    University,
)
from app.modules.programs.schemas import (
    VALUE_SLOT_NAMES,
    EvidenceCreate,
    ProgramSearchFilters,
)


class ProgramNotFoundError(LookupError):
    pass


class RequirementNotFoundError(LookupError):
    pass


class EvidenceNotFoundError(LookupError):
    pass


class ProgramValidationError(ValueError):
    pass


class EvidenceStateError(ValueError):
    pass


class IngestOutcome(StrEnum):
    PUBLISHED_INITIAL = "published_initial"
    CORROBORATED = "corroborated"
    CONFLICT_RECORDED = "conflict_recorded"
    DUPLICATE_IGNORED = "duplicate_ignored"


@dataclass
class EvidenceIngestResult:
    outcome: IngestOutcome
    evidence: RequirementEvidence
    requirement: ProgramRequirement


@dataclass
class RequirementReviewResult:
    decision: ReviewDecision
    evidence: RequirementEvidence
    requirement: ProgramRequirement


@dataclass
class RequirementConflict:
    requirement: ProgramRequirement
    conflicting_evidence: list[RequirementEvidence]


def get_program(*, session: Session, program_id: uuid.UUID) -> Program | None:
    return session.get(Program, program_id)


def get_program_or_raise(*, session: Session, program_id: uuid.UUID) -> Program:
    program = get_program(session=session, program_id=program_id)
    if program is None:
        raise ProgramNotFoundError("项目不存在")
    return program


def get_program_with_university(
    *, session: Session, program_id: uuid.UUID
) -> tuple[Program, University]:
    statement = (
        select(Program, University)
        .join(University, col(Program.university_id) == col(University.id))
        .where(col(Program.id) == program_id)
    )
    row = session.exec(statement).one_or_none()
    if row is None:
        raise ProgramNotFoundError("项目不存在")
    return row


def search_programs(
    *, session: Session, filters: ProgramSearchFilters
) -> tuple[list[tuple[Program, University]], int]:
    conditions = _search_conditions(filters)

    count_statement = (
        select(func.count())
        .select_from(Program)
        .join(University, col(Program.university_id) == col(University.id))
    )
    for condition in conditions:
        count_statement = count_statement.where(condition)
    count = session.exec(count_statement).one()

    statement = select(Program, University).join(
        University, col(Program.university_id) == col(University.id)
    )
    for condition in conditions:
        statement = statement.where(condition)
    statement = (
        statement.order_by(col(University.short_name), col(Program.name))
        .offset(filters.skip)
        .limit(filters.limit)
    )
    rows = list(session.exec(statement).all())
    return rows, count


def _search_conditions(filters: ProgramSearchFilters) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if filters.region is not None:
        conditions.append(col(University.region) == filters.region)
    if filters.university is not None:
        conditions.append(col(University.short_name).ilike(filters.university))
    if filters.degree_type is not None:
        conditions.append(col(Program.degree_type) == filters.degree_type)
    if filters.field_tags:
        conditions.append(
            col(Program.field_tags).op("&&")(
                sa_cast(list(filters.field_tags), ARRAY(String(50)))
            )
        )
    if filters.query:
        pattern = f"%{filters.query}%"
        conditions.append(
            or_(
                col(Program.name).ilike(pattern),
                col(University.name).ilike(pattern),
                col(University.short_name).ilike(pattern),
            )
        )
    if (
        filters.max_tuition is not None
        and filters.tuition_currency is not None
        and filters.application_cycle is not None
    ):
        conditions.append(
            _tuition_within_budget(
                application_cycle=filters.application_cycle,
                max_tuition=filters.max_tuition,
                tuition_currency=filters.tuition_currency,
            )
        )
    return conditions


def _tuition_within_budget(
    *, application_cycle: str, max_tuition: Decimal, tuition_currency: str
) -> ColumnElement[bool]:
    return (
        select(ProgramRequirement.id)
        .where(
            col(ProgramRequirement.program_id) == col(Program.id),
            col(ProgramRequirement.application_cycle) == application_cycle,
            col(ProgramRequirement.field_name) == RequirementFieldName.TUITION,
            col(ProgramRequirement.money_currency) == tuition_currency,
            col(ProgramRequirement.money_amount) <= max_tuition,
        )
        .exists()
    )


def list_evidence_by_id(
    *, session: Session, evidence_ids: list[uuid.UUID]
) -> dict[uuid.UUID, RequirementEvidence]:
    if not evidence_ids:
        return {}
    rows = session.exec(
        select(RequirementEvidence).where(col(RequirementEvidence.id).in_(evidence_ids))
    ).all()
    return {row.id: row for row in rows}


def list_requirements(
    *,
    session: Session,
    program_id: uuid.UUID,
    application_cycle: str | None = None,
) -> list[ProgramRequirement]:
    statement = select(ProgramRequirement).where(
        col(ProgramRequirement.program_id) == program_id
    )
    if application_cycle is not None:
        statement = statement.where(
            col(ProgramRequirement.application_cycle) == application_cycle
        )
    statement = statement.order_by(
        col(ProgramRequirement.application_cycle), col(ProgramRequirement.field_name)
    )
    return list(session.exec(statement).all())


def list_evidence(
    *,
    session: Session,
    program_id: uuid.UUID,
    application_cycle: str | None = None,
    field_name: RequirementFieldName | None = None,
    status: EvidenceStatus | None = None,
) -> list[RequirementEvidence]:
    statement = select(RequirementEvidence).where(
        col(RequirementEvidence.program_id) == program_id
    )
    if application_cycle is not None:
        statement = statement.where(
            col(RequirementEvidence.application_cycle) == application_cycle
        )
    if field_name is not None:
        statement = statement.where(col(RequirementEvidence.field_name) == field_name)
    if status is not None:
        statement = statement.where(col(RequirementEvidence.status) == status)
    statement = statement.order_by(col(RequirementEvidence.captured_at).desc())
    return list(session.exec(statement).all())


def list_conflicts(
    *,
    session: Session,
    program_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[RequirementConflict], int]:
    base = select(ProgramRequirement).where(
        col(ProgramRequirement.status) == RequirementStatus.CONFLICT_PENDING
    )
    count_statement = (
        select(func.count())
        .select_from(ProgramRequirement)
        .where(col(ProgramRequirement.status) == RequirementStatus.CONFLICT_PENDING)
    )
    if program_id is not None:
        base = base.where(col(ProgramRequirement.program_id) == program_id)
        count_statement = count_statement.where(
            col(ProgramRequirement.program_id) == program_id
        )

    count = session.exec(count_statement).one()
    requirements = list(
        session.exec(
            base.order_by(col(ProgramRequirement.updated_at)).offset(skip).limit(limit)
        ).all()
    )

    conflicts = [
        RequirementConflict(
            requirement=requirement,
            conflicting_evidence=_conflicting_evidence(
                session=session, requirement=requirement
            ),
        )
        for requirement in requirements
    ]
    return conflicts, count


def ingest_evidence(
    *,
    session: Session,
    program_id: uuid.UUID,
    evidence_in: EvidenceCreate,
) -> EvidenceIngestResult:
    try:
        program = session.exec(
            select(Program).where(col(Program.id) == program_id).with_for_update()
        ).one_or_none()
        if program is None:
            raise ProgramNotFoundError("项目不存在")

        duplicate = _find_duplicate_evidence(
            session=session, program_id=program_id, evidence_in=evidence_in
        )
        if duplicate is not None:
            requirement = _get_requirement(
                session=session,
                program_id=program_id,
                application_cycle=evidence_in.application_cycle,
                field_name=evidence_in.field_name,
            )
            if requirement is None:
                raise RequirementNotFoundError("项目要求不存在")
            session.commit()
            return EvidenceIngestResult(
                outcome=IngestOutcome.DUPLICATE_IGNORED,
                evidence=duplicate,
                requirement=requirement,
            )

        now = get_datetime_utc()
        evidence = RequirementEvidence(
            program_id=program_id,
            application_cycle=evidence_in.application_cycle,
            field_name=evidence_in.field_name,
            value_type=evidence_in.value_type,
            source_url=evidence_in.source_url,
            source_type=evidence_in.source_type,
            captured_at=evidence_in.captured_at,
            content_hash=evidence_in.content_hash,
            status=EvidenceStatus.UNVERIFIED,
            **_value_slots(evidence_in),
        )
        session.add(evidence)
        session.flush()

        requirement = _get_requirement(
            session=session,
            program_id=program_id,
            application_cycle=evidence_in.application_cycle,
            field_name=evidence_in.field_name,
        )

        if requirement is None:
            requirement = ProgramRequirement(
                program_id=program_id,
                application_cycle=evidence_in.application_cycle,
                field_name=evidence_in.field_name,
                value_type=evidence_in.value_type,
                status=RequirementStatus.PUBLISHED,
                published_evidence_id=evidence.id,
                **_value_slots(evidence_in),
            )
            evidence.status = EvidenceStatus.VERIFIED
            session.add(requirement)
            session.flush()
            _log(
                session=session,
                requirement=requirement,
                evidence=evidence,
                decision=ReviewDecision.INITIAL_PUBLISH,
                old_value=None,
                new_value=_value_json(evidence),
            )
            outcome = IngestOutcome.PUBLISHED_INITIAL
        elif _values_equal(requirement, evidence):
            evidence.status = EvidenceStatus.VERIFIED
            requirement.updated_at = now
            session.add(requirement)
            _log(
                session=session,
                requirement=requirement,
                evidence=evidence,
                decision=ReviewDecision.EVIDENCE_CORROBORATED,
                old_value=_value_json(requirement),
                new_value=_value_json(requirement),
            )
            outcome = IngestOutcome.CORROBORATED
        else:
            # 新来源与当前值不一致时保留已发布值，交给管理员复核。
            evidence.status = EvidenceStatus.CONFLICTED
            requirement.status = RequirementStatus.CONFLICT_PENDING
            requirement.updated_at = now
            session.add(requirement)
            _log(
                session=session,
                requirement=requirement,
                evidence=evidence,
                decision=ReviewDecision.CONFLICT_RECORDED,
                old_value=_value_json(requirement),
                new_value=_value_json(evidence),
            )
            outcome = IngestOutcome.CONFLICT_RECORDED

        session.commit()
        session.refresh(evidence)
        session.refresh(requirement)
        return EvidenceIngestResult(
            outcome=outcome, evidence=evidence, requirement=requirement
        )
    except Exception:
        session.rollback()
        raise


def accept_evidence(
    *,
    session: Session,
    evidence_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    note: str | None = None,
) -> RequirementReviewResult:
    try:
        evidence, requirement = _load_for_review(
            session=session, evidence_id=evidence_id
        )
        now = get_datetime_utc()
        old_value: dict[str, Any] = _value_json(requirement)

        for supporting in _evidence_for_key(
            session=session, requirement=requirement, status=EvidenceStatus.VERIFIED
        ):
            supporting.status = EvidenceStatus.SUPERSEDED
            supporting.updated_at = now
            session.add(supporting)

        for slot, value in _value_slots(evidence).items():
            setattr(requirement, slot, value)
        requirement.published_evidence_id = evidence.id
        requirement.updated_at = now

        evidence.status = EvidenceStatus.VERIFIED
        evidence.reviewed_by = reviewer_id
        evidence.reviewed_at = now
        evidence.review_note = note
        evidence.updated_at = now
        session.add(evidence)

        requirement.status = _remaining_status(
            session=session, requirement=requirement, resolved_evidence_id=evidence.id
        )
        session.add(requirement)

        _log(
            session=session,
            requirement=requirement,
            evidence=evidence,
            decision=ReviewDecision.EVIDENCE_ACCEPTED,
            old_value=old_value,
            new_value=_value_json(evidence),
            reviewed_by=reviewer_id,
            note=note,
        )

        session.commit()
        session.refresh(evidence)
        session.refresh(requirement)
        return RequirementReviewResult(
            decision=ReviewDecision.EVIDENCE_ACCEPTED,
            evidence=evidence,
            requirement=requirement,
        )
    except Exception:
        session.rollback()
        raise


def reject_evidence(
    *,
    session: Session,
    evidence_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    note: str | None = None,
) -> RequirementReviewResult:
    try:
        evidence, requirement = _load_for_review(
            session=session, evidence_id=evidence_id
        )
        now = get_datetime_utc()

        evidence.status = EvidenceStatus.REJECTED
        evidence.reviewed_by = reviewer_id
        evidence.reviewed_at = now
        evidence.review_note = note
        evidence.updated_at = now
        session.add(evidence)

        requirement.status = _remaining_status(
            session=session, requirement=requirement, resolved_evidence_id=evidence.id
        )
        requirement.updated_at = now
        session.add(requirement)

        _log(
            session=session,
            requirement=requirement,
            evidence=evidence,
            decision=ReviewDecision.EVIDENCE_REJECTED,
            old_value=_value_json(requirement),
            new_value=_value_json(requirement),
            reviewed_by=reviewer_id,
            note=note,
        )

        session.commit()
        session.refresh(evidence)
        session.refresh(requirement)
        return RequirementReviewResult(
            decision=ReviewDecision.EVIDENCE_REJECTED,
            evidence=evidence,
            requirement=requirement,
        )
    except Exception:
        session.rollback()
        raise


def _load_for_review(
    *, session: Session, evidence_id: uuid.UUID
) -> tuple[RequirementEvidence, ProgramRequirement]:
    evidence = session.get(RequirementEvidence, evidence_id)
    if evidence is None:
        raise EvidenceNotFoundError("证据不存在")

    program = session.exec(
        select(Program).where(col(Program.id) == evidence.program_id).with_for_update()
    ).one_or_none()
    if program is None:
        raise ProgramNotFoundError("项目不存在")
    session.refresh(evidence)

    if evidence.status is not EvidenceStatus.CONFLICTED:
        raise EvidenceStateError(
            f"Only conflicted evidence can be reviewed, got {evidence.status.value}"
        )

    requirement = _get_requirement(
        session=session,
        program_id=evidence.program_id,
        application_cycle=evidence.application_cycle,
        field_name=evidence.field_name,
    )
    if requirement is None:
        raise RequirementNotFoundError("项目要求不存在")
    return evidence, requirement


def _remaining_status(
    *,
    session: Session,
    requirement: ProgramRequirement,
    resolved_evidence_id: uuid.UUID,
) -> RequirementStatus:
    remaining = [
        row
        for row in _evidence_for_key(
            session=session,
            requirement=requirement,
            status=EvidenceStatus.CONFLICTED,
        )
        if row.id != resolved_evidence_id
    ]
    return (
        RequirementStatus.CONFLICT_PENDING if remaining else RequirementStatus.PUBLISHED
    )


def _conflicting_evidence(
    *, session: Session, requirement: ProgramRequirement
) -> list[RequirementEvidence]:
    return _evidence_for_key(
        session=session, requirement=requirement, status=EvidenceStatus.CONFLICTED
    )


def _evidence_for_key(
    *,
    session: Session,
    requirement: ProgramRequirement,
    status: EvidenceStatus,
) -> list[RequirementEvidence]:
    statement = (
        select(RequirementEvidence)
        .where(col(RequirementEvidence.program_id) == requirement.program_id)
        .where(
            col(RequirementEvidence.application_cycle) == requirement.application_cycle
        )
        .where(col(RequirementEvidence.field_name) == requirement.field_name)
        .where(col(RequirementEvidence.status) == status)
        .order_by(col(RequirementEvidence.captured_at))
    )
    return list(session.exec(statement).all())


def _get_requirement(
    *,
    session: Session,
    program_id: uuid.UUID,
    application_cycle: str,
    field_name: RequirementFieldName,
) -> ProgramRequirement | None:
    statement = (
        select(ProgramRequirement)
        .where(col(ProgramRequirement.program_id) == program_id)
        .where(col(ProgramRequirement.application_cycle) == application_cycle)
        .where(col(ProgramRequirement.field_name) == field_name)
    )
    return session.exec(statement).one_or_none()


def _find_duplicate_evidence(
    *,
    session: Session,
    program_id: uuid.UUID,
    evidence_in: EvidenceCreate,
) -> RequirementEvidence | None:
    statement = (
        select(RequirementEvidence)
        .where(col(RequirementEvidence.program_id) == program_id)
        .where(
            col(RequirementEvidence.application_cycle) == evidence_in.application_cycle
        )
        .where(col(RequirementEvidence.field_name) == evidence_in.field_name)
        .where(col(RequirementEvidence.source_url) == evidence_in.source_url)
        .where(
            col(RequirementEvidence.status).in_(
                [
                    EvidenceStatus.UNVERIFIED,
                    EvidenceStatus.VERIFIED,
                    EvidenceStatus.CONFLICTED,
                ]
            )
        )
    )
    for existing in session.exec(statement).all():
        if _values_equal(existing, evidence_in):
            return existing
    return None


def _log(
    *,
    session: Session,
    requirement: ProgramRequirement,
    evidence: RequirementEvidence | None,
    decision: ReviewDecision,
    old_value: dict[str, Any] | None,
    new_value: dict[str, Any] | None,
    reviewed_by: uuid.UUID | None = None,
    note: str | None = None,
) -> None:
    session.add(
        RequirementReviewLog(
            requirement_id=requirement.id,
            evidence_id=None if evidence is None else evidence.id,
            decision=decision,
            old_value=old_value,
            new_value=new_value,
            reviewed_by=reviewed_by,
            note=note,
        )
    )


ValueHolder = ProgramRequirement | RequirementEvidence | EvidenceCreate


def _value_slots(holder: ValueHolder) -> dict[str, Any]:
    return {slot: getattr(holder, slot) for slot in VALUE_SLOT_NAMES}


def _values_equal(left: ValueHolder, right: ValueHolder) -> bool:
    return _comparable(left) == _comparable(right)


def _comparable(holder: ValueHolder) -> tuple[Any, ...]:
    text_list = holder.text_list_value
    return (
        holder.numeric_value,
        holder.date_value,
        holder.money_amount,
        None if holder.money_currency is None else holder.money_currency.upper(),
        holder.text_value,
        None if text_list is None else tuple(sorted(text_list)),
    )


def _value_json(holder: ValueHolder) -> dict[str, Any]:
    return {slot: _to_json_value(value) for slot, value in _value_slots(holder).items()}


def _to_json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        normalized = value.normalize()
        if normalized == normalized.to_integral_value():
            normalized = normalized.quantize(Decimal(1))
        return format(normalized, "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, list):
        return [_to_json_value(item) for item in value]
    return value
