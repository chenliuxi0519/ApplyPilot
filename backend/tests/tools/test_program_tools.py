import uuid
from datetime import UTC, date, datetime

import pytest
from sqlmodel import Session

from app.harness import ToolErrorCode, ToolExecutionError, ToolRegistry
from app.modules.programs.models import (
    EvidenceSourceType,
    Region,
    RequirementFieldName,
    RequirementStatus,
)
from app.modules.programs.schemas import EvidenceCreate
from app.modules.programs.service import ingest_evidence
from tests.tools.conftest import make_context, run_tool
from tests.utils.program import (
    APPLICATION_CYCLE,
    create_random_program,
    create_random_university,
    ielts_evidence,
    tuition_evidence,
)
from tests.utils.user import create_random_user


def test_search_returns_a_compact_summary(db: Session, registry: ToolRegistry) -> None:
    university = create_random_university(db, region=Region.HONG_KONG)
    program = create_random_program(db, university=university)
    ctx = make_context(db, create_random_user(db))

    output = run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="search_programs",
        arguments={"university": university.short_name, "region": "hong_kong"},
    )

    assert output.count == 1
    summary = output.data[0]
    assert summary.program_id == program.id
    assert summary.university == university.short_name
    assert summary.region is Region.HONG_KONG

    assert not hasattr(summary, "created_at")
    assert not hasattr(summary, "program_url")


def test_search_supports_the_single_currency_budget_filter(
    db: Session, registry: ToolRegistry
) -> None:
    university = create_random_university(db)
    affordable = create_random_program(db, university=university)
    expensive = create_random_program(db, university=university)
    ingest_evidence(
        session=db,
        program_id=affordable.id,
        evidence_in=tuition_evidence(amount="50000", currency="SGD"),
    )
    ingest_evidence(
        session=db,
        program_id=expensive.id,
        evidence_in=tuition_evidence(amount="70000", currency="SGD"),
    )
    ctx = make_context(db, create_random_user(db))

    output = run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="search_programs",
        arguments={
            "university": university.short_name,
            "application_cycle": APPLICATION_CYCLE,
            "max_tuition": "60000",
            "tuition_currency": "SGD",
        },
    )
    assert [row.program_id for row in output.data] == [affordable.id]


def test_requirements_are_flattened_and_carry_status(
    db: Session, registry: ToolRegistry
) -> None:
    program = create_random_program(db)
    ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )
    ingest_evidence(
        session=db,
        program_id=program.id,
        evidence_in=EvidenceCreate(
            application_cycle=APPLICATION_CYCLE,
            field_name=RequirementFieldName.TUITION,
            money_amount=55000,
            money_currency="SGD",
            source_url="https://example.edu/fees",
            source_type=EvidenceSourceType.FEES_PAGE,
            captured_at=datetime(2026, 1, 15, tzinfo=UTC),
        ),
    )
    ctx = make_context(db, create_random_user(db))

    output = run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="get_program_requirements",
        arguments={
            "program_id": str(program.id),
            "application_cycle": APPLICATION_CYCLE,
        },
    )

    values = {row.field_name: row.value for row in output.data}
    assert values[RequirementFieldName.IELTS_OVERALL] == "6.5"
    assert values[RequirementFieldName.TUITION] == "55000 SGD"
    assert all(row.status is RequirementStatus.PUBLISHED for row in output.data)


def test_a_disputed_requirement_is_visible_to_the_agent(
    db: Session, registry: ToolRegistry
) -> None:
    program = create_random_program(db)
    ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )
    ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.0")
    )
    ctx = make_context(db, create_random_user(db))

    output = run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="get_program_requirements",
        arguments={"program_id": str(program.id)},
    )

    ielts = next(
        row
        for row in output.data
        if row.field_name is RequirementFieldName.IELTS_OVERALL
    )
    assert ielts.status is RequirementStatus.CONFLICT_PENDING

    assert ielts.value == "6.5"


def test_a_date_requirement_is_rendered_as_iso(
    db: Session, registry: ToolRegistry
) -> None:
    program = create_random_program(db)
    ingest_evidence(
        session=db,
        program_id=program.id,
        evidence_in=EvidenceCreate(
            application_cycle=APPLICATION_CYCLE,
            field_name=RequirementFieldName.APPLICATION_DEADLINE,
            date_value=date(2027, 1, 15),
            source_url="https://example.edu/deadlines",
            source_type=EvidenceSourceType.ADMISSION_PAGE,
            captured_at=datetime(2026, 1, 15, tzinfo=UTC),
        ),
    )
    ctx = make_context(db, create_random_user(db))

    output = run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="get_program_requirements",
        arguments={"program_id": str(program.id)},
    )
    assert output.data[0].value == "2027-01-15"


def test_unknown_program_is_a_structured_not_found(
    db: Session, registry: ToolRegistry
) -> None:
    ctx = make_context(db, create_random_user(db))
    with pytest.raises(ToolExecutionError) as error:
        run_tool(
            registry=registry,
            ctx=ctx,
            tool_name="get_program_requirements",
            arguments={"program_id": str(uuid.uuid4())},
        )
    assert error.value.code is ToolErrorCode.NOT_FOUND
