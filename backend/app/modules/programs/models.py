from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field, SQLModel

from app.modules.columns import enum_column, get_datetime_utc

APPLICATION_CYCLE_PATTERN = r"^\d{4}/\d{2}$"


class Region(StrEnum):
    SINGAPORE = "singapore"
    HONG_KONG = "hong_kong"
    UNITED_KINGDOM = "united_kingdom"


class DegreeType(StrEnum):
    TAUGHT_MASTER = "taught_master"
    RESEARCH_MASTER = "research_master"
    PHD = "phd"


class RequirementFieldName(StrEnum):
    IELTS_OVERALL = "ielts_overall"
    IELTS_MIN_BAND = "ielts_min_band"
    TOEFL_OVERALL = "toefl_overall"
    GPA_MIN = "gpa_min"
    GPA_SCALE = "gpa_scale"
    WORK_EXPERIENCE_YEARS = "work_experience_years"
    APPLICATION_DEADLINE = "application_deadline"
    TUITION = "tuition"
    DEGREE_BACKGROUND = "degree_background"
    PREREQUISITE_COURSES = "prerequisite_courses"


class RequirementValueType(StrEnum):
    NUMERIC = "numeric"
    DATE = "date"
    MONEY = "money"
    TEXT = "text"
    TEXT_LIST = "text_list"


REQUIREMENT_FIELD_VALUE_TYPES: dict[RequirementFieldName, RequirementValueType] = {
    RequirementFieldName.IELTS_OVERALL: RequirementValueType.NUMERIC,
    RequirementFieldName.IELTS_MIN_BAND: RequirementValueType.NUMERIC,
    RequirementFieldName.TOEFL_OVERALL: RequirementValueType.NUMERIC,
    RequirementFieldName.GPA_MIN: RequirementValueType.NUMERIC,
    RequirementFieldName.GPA_SCALE: RequirementValueType.NUMERIC,
    RequirementFieldName.WORK_EXPERIENCE_YEARS: RequirementValueType.NUMERIC,
    RequirementFieldName.APPLICATION_DEADLINE: RequirementValueType.DATE,
    RequirementFieldName.TUITION: RequirementValueType.MONEY,
    RequirementFieldName.DEGREE_BACKGROUND: RequirementValueType.TEXT,
    RequirementFieldName.PREREQUISITE_COURSES: RequirementValueType.TEXT_LIST,
}


class RequirementStatus(StrEnum):
    PUBLISHED = "published"
    CONFLICT_PENDING = "conflict_pending"


class EvidenceSourceType(StrEnum):
    PROGRAM_PAGE = "program_page"
    ADMISSION_PAGE = "admission_page"
    FEES_PAGE = "fees_page"
    UNIVERSITY_ENGLISH_REQUIREMENT = "university_english_requirement"
    OFFICIAL_PDF = "official_pdf"
    OFFICIAL_FAQ = "official_faq"
    HANDBOOK = "handbook"


class EvidenceStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    CONFLICTED = "conflicted"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class ReviewDecision(StrEnum):
    INITIAL_PUBLISH = "initial_publish"
    EVIDENCE_CORROBORATED = "evidence_corroborated"
    CONFLICT_RECORDED = "conflict_recorded"
    EVIDENCE_ACCEPTED = "evidence_accepted"
    EVIDENCE_REJECTED = "evidence_rejected"


SUPPORTED_CURRENCIES = ("SGD", "HKD", "GBP", "CNY", "USD", "EUR")


def _quoted(values: tuple[str, ...] | list[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _in_check(column: str, enum_type: type[StrEnum]) -> str:
    values = [member.value for member in enum_type]
    return f"{column} IN ({_quoted(values)})"


def _field_value_type_check(column_prefix: str = "") -> str:
    pairs = [
        f"({column_prefix}field_name = '{field.value}' AND "
        f"{column_prefix}value_type = '{value_type.value}')"
        for field, value_type in REQUIREMENT_FIELD_VALUE_TYPES.items()
    ]
    return " OR ".join(pairs)


_VALUE_SLOTS = {
    RequirementValueType.NUMERIC: ("numeric_value",),
    RequirementValueType.DATE: ("date_value",),
    RequirementValueType.MONEY: ("money_amount", "money_currency"),
    RequirementValueType.TEXT: ("text_value",),
    RequirementValueType.TEXT_LIST: ("text_list_value",),
}
_ALL_VALUE_SLOTS = tuple(slot for slots in _VALUE_SLOTS.values() for slot in slots)


def _value_slot_check() -> str:
    branches: list[str] = []
    for value_type, filled in _VALUE_SLOTS.items():
        conditions: list[str] = [f"value_type = '{value_type.value}'"]
        conditions.extend(f"{slot} IS NOT NULL" for slot in filled)
        conditions.extend(
            f"{slot} IS NULL" for slot in _ALL_VALUE_SLOTS if slot not in filled
        )
        branches.append("(" + " AND ".join(conditions) + ")")
    return " OR ".join(branches)


def numeric_value_column() -> Column[Any]:
    return Column(Numeric(12, 3), nullable=True)


def date_value_column() -> Column[Any]:
    return Column(Date(), nullable=True)


def money_amount_column() -> Column[Any]:
    return Column(Numeric(14, 2), nullable=True)


def money_currency_column() -> Column[Any]:
    return Column(String(3), nullable=True)


def text_value_column() -> Column[Any]:
    return Column(String(1000), nullable=True)


def text_list_value_column() -> Column[Any]:
    return Column(ARRAY(String(200)), nullable=True)


class University(SQLModel, table=True):
    __tablename__ = "university"
    __table_args__ = (
        UniqueConstraint("name", name="uq_university_name"),
        UniqueConstraint("short_name", name="uq_university_short_name"),
        CheckConstraint(_in_check("region", Region), name="ck_university_region"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=255, nullable=False)
    short_name: str = Field(max_length=50, nullable=False)
    region: Region = Field(sa_column=enum_column(Region, length=32))
    website_url: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Program(SQLModel, table=True):
    __tablename__ = "program"
    __table_args__ = (
        UniqueConstraint("university_id", "name", name="uq_program_university_name"),
        CheckConstraint(
            _in_check("degree_type", DegreeType), name="ck_program_degree_type"
        ),
        CheckConstraint(
            "duration_months IS NULL OR duration_months > 0",
            name="ck_program_duration_positive",
        ),
        Index("ix_program_university_id", "university_id"),
        Index("ix_program_field_tags", "field_tags", postgresql_using="gin"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    university_id: uuid.UUID = Field(
        foreign_key="university.id",
        ondelete="CASCADE",
        nullable=False,
    )
    name: str = Field(max_length=255, nullable=False)
    degree_type: DegreeType = Field(sa_column=enum_column(DegreeType, length=32))
    field_tags: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(String(length=50)), nullable=False),
    )
    program_url: str | None = Field(default=None, max_length=500)
    duration_months: int | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ProgramRequirement(SQLModel, table=True):
    __tablename__ = "program_requirement"
    __table_args__ = (
        UniqueConstraint(
            "program_id",
            "application_cycle",
            "field_name",
            name="uq_program_requirement_program_cycle_field",
        ),
        CheckConstraint(
            f"application_cycle ~ '{APPLICATION_CYCLE_PATTERN}'",
            name="ck_program_requirement_application_cycle",
        ),
        CheckConstraint(
            _in_check("field_name", RequirementFieldName),
            name="ck_program_requirement_field_name",
        ),
        CheckConstraint(
            _in_check("value_type", RequirementValueType),
            name="ck_program_requirement_value_type",
        ),
        CheckConstraint(
            _in_check("status", RequirementStatus),
            name="ck_program_requirement_status",
        ),
        CheckConstraint(
            _field_value_type_check(),
            name="ck_program_requirement_field_value_type",
        ),
        CheckConstraint(_value_slot_check(), name="ck_program_requirement_value_slot"),
        CheckConstraint(
            f"money_currency IS NULL OR money_currency IN "
            f"({_quoted(SUPPORTED_CURRENCIES)})",
            name="ck_program_requirement_money_currency",
        ),
        CheckConstraint(
            "money_amount IS NULL OR money_amount >= 0",
            name="ck_program_requirement_money_non_negative",
        ),
        Index(
            "ix_program_requirement_program_cycle",
            "program_id",
            "application_cycle",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    program_id: uuid.UUID = Field(
        foreign_key="program.id",
        ondelete="CASCADE",
        nullable=False,
    )
    application_cycle: str = Field(max_length=7, nullable=False)
    field_name: RequirementFieldName = Field(
        sa_column=enum_column(RequirementFieldName, length=64)
    )
    value_type: RequirementValueType = Field(
        sa_column=enum_column(RequirementValueType, length=32)
    )
    numeric_value: Decimal | None = Field(
        default=None, sa_column=numeric_value_column()
    )
    date_value: date | None = Field(default=None, sa_column=date_value_column())
    money_amount: Decimal | None = Field(default=None, sa_column=money_amount_column())
    money_currency: str | None = Field(default=None, sa_column=money_currency_column())
    text_value: str | None = Field(default=None, sa_column=text_value_column())
    text_list_value: list[str] | None = Field(
        default=None, sa_column=text_list_value_column()
    )
    status: RequirementStatus = Field(
        default=RequirementStatus.PUBLISHED,
        sa_column=enum_column(RequirementStatus, length=32),
    )
    published_evidence_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="requirement_evidence.id",
        ondelete="SET NULL",
        nullable=True,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class RequirementEvidence(SQLModel, table=True):
    __tablename__ = "requirement_evidence"
    __table_args__ = (
        CheckConstraint(
            f"application_cycle ~ '{APPLICATION_CYCLE_PATTERN}'",
            name="ck_requirement_evidence_application_cycle",
        ),
        CheckConstraint(
            _in_check("field_name", RequirementFieldName),
            name="ck_requirement_evidence_field_name",
        ),
        CheckConstraint(
            _in_check("value_type", RequirementValueType),
            name="ck_requirement_evidence_value_type",
        ),
        CheckConstraint(
            _in_check("source_type", EvidenceSourceType),
            name="ck_requirement_evidence_source_type",
        ),
        CheckConstraint(
            _in_check("status", EvidenceStatus),
            name="ck_requirement_evidence_status",
        ),
        CheckConstraint(
            _field_value_type_check(),
            name="ck_requirement_evidence_field_value_type",
        ),
        CheckConstraint(_value_slot_check(), name="ck_requirement_evidence_value_slot"),
        CheckConstraint(
            f"money_currency IS NULL OR money_currency IN "
            f"({_quoted(SUPPORTED_CURRENCIES)})",
            name="ck_requirement_evidence_money_currency",
        ),
        CheckConstraint(
            "money_amount IS NULL OR money_amount >= 0",
            name="ck_requirement_evidence_money_non_negative",
        ),
        Index(
            "ix_requirement_evidence_program_cycle_field_status",
            "program_id",
            "application_cycle",
            "field_name",
            "status",
        ),
        Index("ix_requirement_evidence_status", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    program_id: uuid.UUID = Field(
        foreign_key="program.id",
        ondelete="CASCADE",
        nullable=False,
    )
    application_cycle: str = Field(max_length=7, nullable=False)
    field_name: RequirementFieldName = Field(
        sa_column=enum_column(RequirementFieldName, length=64)
    )
    value_type: RequirementValueType = Field(
        sa_column=enum_column(RequirementValueType, length=32)
    )
    numeric_value: Decimal | None = Field(
        default=None, sa_column=numeric_value_column()
    )
    date_value: date | None = Field(default=None, sa_column=date_value_column())
    money_amount: Decimal | None = Field(default=None, sa_column=money_amount_column())
    money_currency: str | None = Field(default=None, sa_column=money_currency_column())
    text_value: str | None = Field(default=None, sa_column=text_value_column())
    text_list_value: list[str] | None = Field(
        default=None, sa_column=text_list_value_column()
    )
    source_url: str = Field(max_length=1000, nullable=False)
    source_type: EvidenceSourceType = Field(
        sa_column=enum_column(EvidenceSourceType, length=64)
    )
    captured_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    content_hash: str | None = Field(default=None, max_length=128)
    status: EvidenceStatus = Field(
        default=EvidenceStatus.UNVERIFIED,
        sa_column=enum_column(EvidenceStatus, length=32),
    )
    reviewed_by: uuid.UUID | None = Field(
        default=None,
        foreign_key="user.id",
        ondelete="SET NULL",
        nullable=True,
    )
    reviewed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    review_note: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class RequirementReviewLog(SQLModel, table=True):
    __tablename__ = "requirement_review_log"
    __table_args__ = (
        CheckConstraint(
            _in_check("decision", ReviewDecision),
            name="ck_requirement_review_log_decision",
        ),
        Index(
            "ix_requirement_review_log_requirement_created",
            "requirement_id",
            "created_at",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    requirement_id: uuid.UUID = Field(
        foreign_key="program_requirement.id",
        ondelete="CASCADE",
        nullable=False,
    )
    evidence_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="requirement_evidence.id",
        ondelete="SET NULL",
        nullable=True,
    )
    decision: ReviewDecision = Field(sa_column=enum_column(ReviewDecision, length=32))
    old_value: Any | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    new_value: Any | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    reviewed_by: uuid.UUID | None = Field(
        default=None,
        foreign_key="user.id",
        ondelete="SET NULL",
        nullable=True,
    )
    note: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
