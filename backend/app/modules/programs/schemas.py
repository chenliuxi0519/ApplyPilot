import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import StringConstraints, model_validator
from sqlmodel import Field, SQLModel

from app.modules.columns import get_datetime_utc
from app.modules.programs.models import (
    REQUIREMENT_FIELD_VALUE_TYPES,
    SUPPORTED_CURRENCIES,
    DegreeType,
    EvidenceSourceType,
    EvidenceStatus,
    Region,
    RequirementFieldName,
    RequirementStatus,
    RequirementValueType,
    ReviewDecision,
)

ApplicationCycle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^\d{4}/\d{2}$"),
]
FieldTag = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
]
TextListItem = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]

VALUE_SLOT_NAMES = (
    "numeric_value",
    "date_value",
    "money_amount",
    "money_currency",
    "text_value",
    "text_list_value",
)


class RequirementValueFields(SQLModel):
    numeric_value: Decimal | None = Field(default=None, decimal_places=3)
    date_value: date | None = None
    money_amount: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    money_currency: str | None = Field(default=None, min_length=3, max_length=3)
    text_value: str | None = Field(default=None, max_length=1000)
    text_list_value: list[TextListItem] | None = Field(default=None, max_length=50)


class EvidenceCreate(RequirementValueFields):
    application_cycle: ApplicationCycle
    field_name: RequirementFieldName
    source_url: str = Field(min_length=1, max_length=1000)
    source_type: EvidenceSourceType
    captured_at: datetime
    content_hash: str | None = Field(default=None, max_length=128)

    @property
    def value_type(self) -> RequirementValueType:
        return REQUIREMENT_FIELD_VALUE_TYPES[self.field_name]

    @model_validator(mode="after")
    def validate_value(self) -> "EvidenceCreate":
        expected = REQUIREMENT_FIELD_VALUE_TYPES[self.field_name]
        required = _required_slots(expected)
        for slot in VALUE_SLOT_NAMES:
            value = getattr(self, slot)
            if slot in required and value is None:
                raise ValueError(
                    f"{self.field_name.value} requires {slot} to be provided"
                )
            if slot not in required and value is not None:
                raise ValueError(f"{self.field_name.value} does not accept {slot}")

        if self.money_currency is not None:
            currency = self.money_currency.upper()
            if currency not in SUPPORTED_CURRENCIES:
                raise ValueError(
                    f"money_currency must be one of {SUPPORTED_CURRENCIES}"
                )
            self.money_currency = currency

        if self.text_list_value is not None and not self.text_list_value:
            raise ValueError("文本列表不能为空")

        if self.captured_at.tzinfo is None:
            raise ValueError("采集时间必须包含时区")
        self.captured_at = self.captured_at.astimezone(UTC)
        if self.captured_at > get_datetime_utc():
            raise ValueError("采集时间不能晚于当前时间")
        return self


def _required_slots(value_type: RequirementValueType) -> tuple[str, ...]:
    if value_type is RequirementValueType.NUMERIC:
        return ("numeric_value",)
    if value_type is RequirementValueType.DATE:
        return ("date_value",)
    if value_type is RequirementValueType.MONEY:
        return ("money_amount", "money_currency")
    if value_type is RequirementValueType.TEXT:
        return ("text_value",)
    return ("text_list_value",)


class EvidenceReview(SQLModel):
    note: str | None = Field(default=None, max_length=2000)


class ProgramSearchFilters(SQLModel):
    region: Region | None = None
    university: str | None = Field(default=None, max_length=50)
    degree_type: DegreeType | None = None
    field_tags: list[FieldTag] | None = Field(default=None, max_length=10)
    query: str | None = Field(default=None, max_length=255)
    application_cycle: ApplicationCycle | None = None
    max_tuition: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    tuition_currency: str | None = Field(default=None, min_length=3, max_length=3)
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)

    @model_validator(mode="after")
    def validate_filters(self) -> "ProgramSearchFilters":
        if self.tuition_currency is not None:
            currency = self.tuition_currency.upper()
            if currency not in SUPPORTED_CURRENCIES:
                raise ValueError(f"学费币种必须是以下之一：{SUPPORTED_CURRENCIES}")
            self.tuition_currency = currency

        if self.max_tuition is not None and (
            self.tuition_currency is None or self.application_cycle is None
        ):
            raise ValueError("按最高学费筛选时必须同时提供学费币种和申请季")
        return self


class UniversityPublic(SQLModel):
    id: uuid.UUID
    name: str
    short_name: str
    region: Region
    website_url: str | None


class ProgramPublic(SQLModel):
    id: uuid.UUID
    university_id: uuid.UUID
    name: str
    degree_type: DegreeType
    field_tags: list[str]
    program_url: str | None
    duration_months: int | None
    created_at: datetime
    updated_at: datetime


class ProgramWithUniversityPublic(ProgramPublic):
    university: UniversityPublic


class ProgramsPublic(SQLModel):
    data: list[ProgramWithUniversityPublic]
    count: int


class RequirementPublic(RequirementValueFields):
    id: uuid.UUID
    program_id: uuid.UUID
    application_cycle: str
    field_name: RequirementFieldName
    value_type: RequirementValueType
    status: RequirementStatus
    published_evidence_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class RequirementsPublic(SQLModel):
    data: list[RequirementPublic]
    count: int


class EvidencePublic(RequirementValueFields):
    id: uuid.UUID
    program_id: uuid.UUID
    application_cycle: str
    field_name: RequirementFieldName
    value_type: RequirementValueType
    source_url: str
    source_type: EvidenceSourceType
    captured_at: datetime
    content_hash: str | None
    status: EvidenceStatus
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime
    updated_at: datetime


class EvidenceListPublic(SQLModel):
    data: list[EvidencePublic]
    count: int


class EvidenceIngestPublic(SQLModel):
    outcome: str
    evidence: EvidencePublic
    requirement: RequirementPublic


class RequirementReviewLogPublic(SQLModel):
    id: uuid.UUID
    requirement_id: uuid.UUID
    evidence_id: uuid.UUID | None
    decision: ReviewDecision
    old_value: Any | None
    new_value: Any | None
    reviewed_by: uuid.UUID | None
    note: str | None
    created_at: datetime


class RequirementReviewPublic(SQLModel):
    decision: ReviewDecision
    evidence: EvidencePublic
    requirement: RequirementPublic


class ConflictPublic(SQLModel):
    requirement: RequirementPublic
    conflicting_evidence: list[EvidencePublic]


class ConflictsPublic(SQLModel):
    data: list[ConflictPublic]
    count: int
