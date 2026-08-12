import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

import pytest
from sqlalchemy.exc import IntegrityError, StatementError
from sqlmodel import Session, col, select

from app.core.db import engine
from app.modules.programs.models import (
    EvidenceSourceType,
    EvidenceStatus,
    Program,
    ProgramRequirement,
    RequirementEvidence,
    RequirementFieldName,
    RequirementReviewLog,
    RequirementStatus,
    RequirementValueType,
    ReviewDecision,
    University,
)
from app.modules.programs.service import (
    EvidenceNotFoundError,
    EvidenceStateError,
    IngestOutcome,
    ProgramNotFoundError,
    accept_evidence,
    ingest_evidence,
    list_conflicts,
    reject_evidence,
)
from tests.utils.program import (
    APPLICATION_CYCLE,
    create_random_program,
    create_random_university,
    ielts_evidence,
)
from tests.utils.user import create_random_user


def _requirement(db: Session, program: Program) -> ProgramRequirement:
    return db.exec(
        select(ProgramRequirement).where(
            col(ProgramRequirement.program_id) == program.id
        )
    ).one()


def _logs(db: Session, requirement_id: uuid.UUID) -> list[RequirementReviewLog]:
    return list(
        db.exec(
            select(RequirementReviewLog)
            .where(col(RequirementReviewLog.requirement_id) == requirement_id)
            .order_by(col(RequirementReviewLog.created_at))
        ).all()
    )


def test_first_evidence_publishes_requirement(db: Session) -> None:
    program = create_random_program(db)
    result = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )

    assert result.outcome is IngestOutcome.PUBLISHED_INITIAL
    assert result.evidence.status is EvidenceStatus.VERIFIED
    assert result.requirement.status is RequirementStatus.PUBLISHED
    assert result.requirement.numeric_value == Decimal("6.5")
    assert result.requirement.value_type is RequirementValueType.NUMERIC
    assert result.requirement.published_evidence_id == result.evidence.id

    logs = _logs(db, result.requirement.id)
    assert [log.decision for log in logs] == [ReviewDecision.INITIAL_PUBLISH]
    assert logs[0].old_value is None
    assert logs[0].new_value is not None
    assert logs[0].new_value["numeric_value"] == "6.5"


def test_matching_source_corroborates_without_changing_value(db: Session) -> None:
    program = create_random_program(db)
    first = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )
    second = ingest_evidence(
        session=db,
        program_id=program.id,
        evidence_in=ielts_evidence(
            overall="6.500", source_type=EvidenceSourceType.OFFICIAL_PDF
        ),
    )

    assert second.outcome is IngestOutcome.CORROBORATED
    assert second.evidence.status is EvidenceStatus.VERIFIED
    assert second.requirement.status is RequirementStatus.PUBLISHED
    assert second.requirement.numeric_value == Decimal("6.5")

    assert second.requirement.published_evidence_id == first.evidence.id
    assert [log.decision for log in _logs(db, second.requirement.id)] == [
        ReviewDecision.INITIAL_PUBLISH,
        ReviewDecision.EVIDENCE_CORROBORATED,
    ]


def test_disagreeing_source_creates_conflict_without_overwriting(db: Session) -> None:
    program = create_random_program(db)
    published = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )
    conflict = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.0")
    )

    assert conflict.outcome is IngestOutcome.CONFLICT_RECORDED
    assert conflict.evidence.status is EvidenceStatus.CONFLICTED
    assert conflict.requirement.status is RequirementStatus.CONFLICT_PENDING

    assert conflict.requirement.numeric_value == Decimal("6.5")
    assert conflict.requirement.published_evidence_id == published.evidence.id

    logs = _logs(db, conflict.requirement.id)
    assert logs[-1].decision is ReviewDecision.CONFLICT_RECORDED
    assert logs[-1].old_value is not None
    assert logs[-1].new_value is not None
    assert logs[-1].old_value["numeric_value"] == "6.5"
    assert logs[-1].new_value["numeric_value"] == "7"


def test_reposting_same_url_and_value_is_idempotent(db: Session) -> None:
    program = create_random_program(db)
    url = "https://example.edu/msc-ai/admissions"
    first = ingest_evidence(
        session=db,
        program_id=program.id,
        evidence_in=ielts_evidence(overall="6.5", source_url=url),
    )
    repeat = ingest_evidence(
        session=db,
        program_id=program.id,
        evidence_in=ielts_evidence(overall="6.5", source_url=url),
    )

    assert repeat.outcome is IngestOutcome.DUPLICATE_IGNORED
    assert repeat.evidence.id == first.evidence.id
    evidence_rows = db.exec(
        select(RequirementEvidence).where(
            col(RequirementEvidence.program_id) == program.id
        )
    ).all()
    assert len(evidence_rows) == 1


def test_accepting_evidence_publishes_new_value(db: Session) -> None:
    reviewer = create_random_user(db)
    program = create_random_program(db)
    published = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )
    conflict = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.0")
    )

    result = accept_evidence(
        session=db,
        evidence_id=conflict.evidence.id,
        reviewer_id=reviewer.id,
        note="2027 cycle raised the requirement",
    )

    assert result.decision is ReviewDecision.EVIDENCE_ACCEPTED
    assert result.requirement.numeric_value == Decimal("7.0")
    assert result.requirement.status is RequirementStatus.PUBLISHED
    assert result.requirement.published_evidence_id == conflict.evidence.id
    assert result.evidence.status is EvidenceStatus.VERIFIED
    assert result.evidence.reviewed_by == reviewer.id
    assert result.evidence.reviewed_at is not None

    db.refresh(published.evidence)
    assert published.evidence.status is EvidenceStatus.SUPERSEDED

    logs = _logs(db, result.requirement.id)
    assert logs[-1].decision is ReviewDecision.EVIDENCE_ACCEPTED
    assert logs[-1].old_value is not None
    assert logs[-1].new_value is not None
    assert logs[-1].old_value["numeric_value"] == "6.5"
    assert logs[-1].new_value["numeric_value"] == "7"
    assert logs[-1].reviewed_by == reviewer.id


def test_rejecting_evidence_keeps_published_value(db: Session) -> None:
    reviewer = create_random_user(db)
    program = create_random_program(db)
    published = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )
    conflict = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.0")
    )

    result = reject_evidence(
        session=db,
        evidence_id=conflict.evidence.id,
        reviewer_id=reviewer.id,
        note="Community page, not an official source",
    )

    assert result.decision is ReviewDecision.EVIDENCE_REJECTED
    assert result.requirement.numeric_value == Decimal("6.5")
    assert result.requirement.status is RequirementStatus.PUBLISHED
    assert result.requirement.published_evidence_id == published.evidence.id
    assert result.evidence.status is EvidenceStatus.REJECTED

    db.refresh(published.evidence)
    assert published.evidence.status is EvidenceStatus.VERIFIED


def test_requirement_stays_pending_until_every_conflict_is_resolved(
    db: Session,
) -> None:
    reviewer = create_random_user(db)
    program = create_random_program(db)
    ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )
    first = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.0")
    )
    second = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.5")
    )

    after_first = reject_evidence(
        session=db, evidence_id=first.evidence.id, reviewer_id=reviewer.id
    )
    assert after_first.requirement.status is RequirementStatus.CONFLICT_PENDING

    after_second = reject_evidence(
        session=db, evidence_id=second.evidence.id, reviewer_id=reviewer.id
    )
    assert after_second.requirement.status is RequirementStatus.PUBLISHED


def test_reviewing_non_conflicted_evidence_is_refused(db: Session) -> None:
    reviewer = create_random_user(db)
    program = create_random_program(db)
    published = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )

    with pytest.raises(EvidenceStateError):
        accept_evidence(
            session=db,
            evidence_id=published.evidence.id,
            reviewer_id=reviewer.id,
        )


def test_reviewing_the_same_conflict_twice_is_refused(db: Session) -> None:
    reviewer = create_random_user(db)
    program = create_random_program(db)
    ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )
    conflict = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.0")
    )
    accept_evidence(
        session=db, evidence_id=conflict.evidence.id, reviewer_id=reviewer.id
    )

    with pytest.raises(EvidenceStateError):
        accept_evidence(
            session=db, evidence_id=conflict.evidence.id, reviewer_id=reviewer.id
        )


def test_reviewing_unknown_evidence_raises(db: Session) -> None:
    reviewer = create_random_user(db)
    with pytest.raises(EvidenceNotFoundError):
        accept_evidence(session=db, evidence_id=uuid.uuid4(), reviewer_id=reviewer.id)


def test_ingesting_for_unknown_program_raises(db: Session) -> None:
    with pytest.raises(ProgramNotFoundError):
        ingest_evidence(
            session=db, program_id=uuid.uuid4(), evidence_in=ielts_evidence()
        )


def test_conflict_queue_lists_pending_requirements(db: Session) -> None:
    program = create_random_program(db)
    ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )
    conflict = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.0")
    )

    conflicts, count = list_conflicts(session=db, program_id=program.id)
    assert count == 1
    assert len(conflicts) == 1
    assert conflicts[0].requirement.id == conflict.requirement.id
    assert [row.id for row in conflicts[0].conflicting_evidence] == [
        conflict.evidence.id
    ]


def test_failed_ingest_rolls_back_the_whole_transaction(db: Session) -> None:
    program = create_random_program(db)
    evidence_in = ielts_evidence(overall="6.5")
    evidence_in.source_type = cast(EvidenceSourceType, "wikipedia")

    with pytest.raises(StatementError):
        ingest_evidence(session=db, program_id=program.id, evidence_in=evidence_in)

    assert (
        db.exec(
            select(RequirementEvidence).where(
                col(RequirementEvidence.program_id) == program.id
            )
        ).all()
        == []
    )
    assert (
        db.exec(
            select(ProgramRequirement).where(
                col(ProgramRequirement.program_id) == program.id
            )
        ).all()
        == []
    )


def test_concurrent_first_ingests_create_one_requirement(db: Session) -> None:
    program = create_random_program(db)
    program_id = program.id

    def ingest(overall: str) -> None:
        with Session(engine) as session:
            ingest_evidence(
                session=session,
                program_id=program_id,
                evidence_in=ielts_evidence(overall=overall),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(ingest, "6.5"), executor.submit(ingest, "7.0")]
        for future in futures:
            future.result()

    db.expire_all()
    requirements = db.exec(
        select(ProgramRequirement).where(
            col(ProgramRequirement.program_id) == program_id
        )
    ).all()
    assert len(requirements) == 1

    assert requirements[0].status is RequirementStatus.CONFLICT_PENDING


def test_database_enforces_unique_requirement_per_cycle_and_field(
    db: Session,
) -> None:
    program = create_random_program(db)
    for _ in range(2):
        db.add(
            ProgramRequirement(
                program_id=program.id,
                application_cycle=APPLICATION_CYCLE,
                field_name=RequirementFieldName.IELTS_OVERALL,
                value_type=RequirementValueType.NUMERIC,
                numeric_value=Decimal("6.5"),
            )
        )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_rejects_value_in_the_wrong_slot(db: Session) -> None:
    program = create_random_program(db)
    db.add(
        ProgramRequirement(
            program_id=program.id,
            application_cycle=APPLICATION_CYCLE,
            field_name=RequirementFieldName.IELTS_OVERALL,
            value_type=RequirementValueType.NUMERIC,
            text_value="6.5 overall",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_rejects_field_and_value_type_mismatch(db: Session) -> None:
    program = create_random_program(db)
    db.add(
        ProgramRequirement(
            program_id=program.id,
            application_cycle=APPLICATION_CYCLE,
            field_name=RequirementFieldName.APPLICATION_DEADLINE,
            value_type=RequirementValueType.NUMERIC,
            numeric_value=Decimal("20260115"),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_rejects_malformed_application_cycle(db: Session) -> None:
    program = create_random_program(db)
    db.add(
        ProgramRequirement(
            program_id=program.id,
            application_cycle="2026",
            field_name=RequirementFieldName.APPLICATION_DEADLINE,
            value_type=RequirementValueType.DATE,
            date_value=date(2026, 1, 15),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_rejects_unsupported_currency(db: Session) -> None:
    program = create_random_program(db)
    db.add(
        ProgramRequirement(
            program_id=program.id,
            application_cycle=APPLICATION_CYCLE,
            field_name=RequirementFieldName.TUITION,
            value_type=RequirementValueType.MONEY,
            money_amount=Decimal("55000"),
            money_currency="JPY",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_rejects_negative_tuition(db: Session) -> None:
    program = create_random_program(db)
    db.add(
        ProgramRequirement(
            program_id=program.id,
            application_cycle=APPLICATION_CYCLE,
            field_name=RequirementFieldName.TUITION,
            value_type=RequirementValueType.MONEY,
            money_amount=Decimal("-1"),
            money_currency="SGD",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_enforces_program_foreign_key(db: Session) -> None:
    db.add(
        RequirementEvidence(
            program_id=uuid.uuid4(),
            application_cycle=APPLICATION_CYCLE,
            field_name=RequirementFieldName.IELTS_OVERALL,
            value_type=RequirementValueType.NUMERIC,
            numeric_value=Decimal("6.5"),
            source_url="https://example.edu/x",
            source_type=EvidenceSourceType.PROGRAM_PAGE,
            captured_at=datetime(2026, 1, 15, tzinfo=UTC),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_deleting_university_cascades_the_whole_domain(db: Session) -> None:
    reviewer = create_random_user(db)
    university = create_random_university(db)
    program = create_random_program(db, university=university)
    ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )
    conflict = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.0")
    )
    accept_evidence(
        session=db, evidence_id=conflict.evidence.id, reviewer_id=reviewer.id
    )
    requirement_id = conflict.requirement.id
    program_id = program.id

    db.delete(university)
    db.commit()

    assert db.get(Program, program_id) is None
    assert db.get(ProgramRequirement, requirement_id) is None
    assert (
        db.exec(
            select(RequirementEvidence).where(
                col(RequirementEvidence.program_id) == program_id
            )
        ).all()
        == []
    )
    assert (
        db.exec(
            select(RequirementReviewLog).where(
                col(RequirementReviewLog.requirement_id) == requirement_id
            )
        ).all()
        == []
    )


def test_deleting_reviewer_keeps_the_audit_row(db: Session) -> None:
    reviewer = create_random_user(db)
    program = create_random_program(db)
    ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )
    conflict = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.0")
    )
    result = accept_evidence(
        session=db, evidence_id=conflict.evidence.id, reviewer_id=reviewer.id
    )
    evidence_id = result.evidence.id

    db.delete(reviewer)
    db.commit()
    db.expire_all()

    evidence = db.get(RequirementEvidence, evidence_id)
    assert evidence is not None
    assert evidence.reviewed_by is None
    assert evidence.status is EvidenceStatus.VERIFIED


def test_deleting_program_keeps_other_universities(db: Session) -> None:
    kept = create_random_university(db)
    create_random_program(db, university=kept)
    other = create_random_program(db)

    db.delete(other)
    db.commit()

    assert db.get(University, kept.id) is not None
