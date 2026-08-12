from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Session

from app.modules.programs.models import (
    DegreeType,
    EvidenceSourceType,
    Program,
    Region,
    RequirementFieldName,
    University,
)
from app.modules.programs.schemas import EvidenceCreate
from tests.utils.utils import random_lower_string

APPLICATION_CYCLE = "2026/27"


def create_random_university(
    db: Session, *, region: Region = Region.SINGAPORE
) -> University:
    university = University(
        name=f"University of {random_lower_string()}",
        short_name=random_lower_string()[:20],
        region=region,
    )
    db.add(university)
    db.commit()
    db.refresh(university)
    return university


def create_random_program(
    db: Session,
    *,
    university: University | None = None,
    field_tags: list[str] | None = None,
    degree_type: DegreeType = DegreeType.TAUGHT_MASTER,
) -> Program:
    if university is None:
        university = create_random_university(db)
    program = Program(
        university_id=university.id,
        name=f"MSc {random_lower_string()}",
        degree_type=degree_type,
        field_tags=["ai"] if field_tags is None else field_tags,
    )
    db.add(program)
    db.commit()
    db.refresh(program)
    return program


def ielts_evidence(
    *,
    overall: str = "6.5",
    source_url: str | None = None,
    source_type: EvidenceSourceType = EvidenceSourceType.PROGRAM_PAGE,
    application_cycle: str = APPLICATION_CYCLE,
) -> EvidenceCreate:
    return EvidenceCreate(
        application_cycle=application_cycle,
        field_name=RequirementFieldName.IELTS_OVERALL,
        numeric_value=Decimal(overall),
        source_url=source_url or f"https://example.edu/{random_lower_string()}",
        source_type=source_type,
        captured_at=datetime(2026, 1, 15, tzinfo=UTC),
    )


def tuition_evidence(
    *,
    amount: str,
    currency: str,
    source_url: str | None = None,
    application_cycle: str = APPLICATION_CYCLE,
) -> EvidenceCreate:
    return EvidenceCreate(
        application_cycle=application_cycle,
        field_name=RequirementFieldName.TUITION,
        money_amount=Decimal(amount),
        money_currency=currency,
        source_url=source_url or f"https://example.edu/{random_lower_string()}",
        source_type=EvidenceSourceType.FEES_PAGE,
        captured_at=datetime(2026, 1, 15, tzinfo=UTC),
    )
