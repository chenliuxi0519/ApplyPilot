from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.programs.models import (
    EvidenceSourceType,
    RequirementFieldName,
    RequirementValueType,
)
from app.modules.programs.schemas import EvidenceCreate, ProgramSearchFilters

CAPTURED_AT = datetime(2026, 1, 15, tzinfo=UTC)


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "application_cycle": "2026/27",
        "field_name": RequirementFieldName.IELTS_OVERALL,
        "numeric_value": Decimal("6.5"),
        "source_url": "https://example.edu/admissions",
        "source_type": EvidenceSourceType.PROGRAM_PAGE,
        "captured_at": CAPTURED_AT,
    }
    payload.update(overrides)
    return payload


def test_numeric_field_derives_value_type() -> None:
    evidence = EvidenceCreate(**_payload())  # type: ignore[arg-type]
    assert evidence.value_type is RequirementValueType.NUMERIC


def test_money_field_derives_value_type() -> None:
    evidence = EvidenceCreate(
        **_payload(
            field_name=RequirementFieldName.TUITION,
            numeric_value=None,
            money_amount=Decimal("55000"),
            money_currency="sgd",
        )  # type: ignore[arg-type]
    )
    assert evidence.value_type is RequirementValueType.MONEY
    assert evidence.money_currency == "SGD"


def test_missing_required_slot_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceCreate(**_payload(numeric_value=None))  # type: ignore[arg-type]


def test_slot_not_belonging_to_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceCreate(**_payload(text_value="6.5 overall"))  # type: ignore[arg-type]


def test_money_without_currency_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceCreate(
            **_payload(
                field_name=RequirementFieldName.TUITION,
                numeric_value=None,
                money_amount=Decimal("55000"),
            )  # type: ignore[arg-type]
        )


def test_unsupported_currency_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceCreate(
            **_payload(
                field_name=RequirementFieldName.TUITION,
                numeric_value=None,
                money_amount=Decimal("55000"),
                money_currency="JPY",
            )  # type: ignore[arg-type]
        )


def test_empty_text_list_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceCreate(
            **_payload(
                field_name=RequirementFieldName.PREREQUISITE_COURSES,
                numeric_value=None,
                text_list_value=[],
            )  # type: ignore[arg-type]
        )


def test_naive_captured_at_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceCreate(**_payload(captured_at=datetime(2026, 1, 15)))  # type: ignore[arg-type]


def test_future_captured_at_is_rejected() -> None:
    future = datetime.now(UTC) + timedelta(days=1)
    with pytest.raises(ValidationError):
        EvidenceCreate(**_payload(captured_at=future))  # type: ignore[arg-type]


def test_malformed_application_cycle_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceCreate(**_payload(application_cycle="2026-2027"))  # type: ignore[arg-type]


def test_budget_filter_requires_currency_and_cycle() -> None:
    with pytest.raises(ValidationError):
        ProgramSearchFilters(max_tuition=Decimal("50000"))
    with pytest.raises(ValidationError):
        ProgramSearchFilters(max_tuition=Decimal("50000"), tuition_currency="SGD")
    with pytest.raises(ValidationError):
        ProgramSearchFilters(max_tuition=Decimal("50000"), application_cycle="2026/27")


def test_budget_filter_rejects_unsupported_currency() -> None:
    with pytest.raises(ValidationError):
        ProgramSearchFilters(
            max_tuition=Decimal("50000"),
            tuition_currency="JPY",
            application_cycle="2026/27",
        )


def test_budget_filter_normalizes_currency() -> None:
    filters = ProgramSearchFilters(
        max_tuition=Decimal("50000"),
        tuition_currency="sgd",
        application_cycle="2026/27",
    )
    assert filters.tuition_currency == "SGD"
    assert filters.limit == 50
