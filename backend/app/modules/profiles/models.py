from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field, Relationship, SQLModel

from app.models import User
from app.modules.columns import enum_column, get_datetime_utc

__all__ = [
    "ProfileFieldHistory",
    "ProfileFieldName",
    "ProfileFieldSource",
    "ProfileVerificationStatus",
    "UserProfile",
    "enum_column",
    "get_datetime_utc",
]


class ProfileFieldSource(StrEnum):
    USER_EXPLICIT = "user_explicit"
    AGENT_EXTRACTED = "agent_extracted"


class ProfileVerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    USER_CONFIRMED = "user_confirmed"


class ProfileFieldName(StrEnum):
    UNDERGRADUATE_UNIVERSITY = "undergraduate_university"
    UNDERGRADUATE_MAJOR = "undergraduate_major"
    GPA_VALUE = "gpa_value"
    GPA_SCALE = "gpa_scale"
    IELTS_OVERALL = "ielts_overall"
    WORK_EXPERIENCE_YEARS = "work_experience_years"
    EXPERIENCE_SUMMARY = "experience_summary"
    BUDGET_CNY = "budget_cny"
    TARGET_REGIONS = "target_regions"
    TARGET_FIELDS = "target_fields"
    CAREER_GOAL = "career_goal"


class UserProfile(SQLModel, table=True):
    __tablename__ = "user_profile"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_profile_user_id"),
        CheckConstraint(
            "(gpa_value IS NULL AND gpa_scale IS NULL) OR "
            "(gpa_value IS NOT NULL AND gpa_scale IS NOT NULL)",
            name="ck_user_profile_gpa_pair",
        ),
        CheckConstraint(
            "gpa_value IS NULL OR gpa_value >= 0",
            name="ck_user_profile_gpa_non_negative",
        ),
        CheckConstraint(
            "gpa_scale IS NULL OR gpa_scale > 0",
            name="ck_user_profile_gpa_scale_positive",
        ),
        CheckConstraint(
            "gpa_value IS NULL OR gpa_value <= gpa_scale",
            name="ck_user_profile_gpa_within_scale",
        ),
        CheckConstraint(
            "ielts_overall IS NULL OR (ielts_overall >= 0 AND ielts_overall <= 9)",
            name="ck_user_profile_ielts_range",
        ),
        CheckConstraint(
            "work_experience_years IS NULL OR "
            "(work_experience_years >= 0 AND work_experience_years <= 60)",
            name="ck_user_profile_work_experience_range",
        ),
        CheckConstraint(
            "budget_cny IS NULL OR budget_cny >= 0",
            name="ck_user_profile_budget_non_negative",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id",
        ondelete="CASCADE",
        nullable=False,
    )
    undergraduate_university: str | None = Field(default=None, max_length=255)
    undergraduate_major: str | None = Field(default=None, max_length=255)
    gpa_value: Decimal | None = Field(
        default=None,
        sa_column=Column(Numeric(5, 2), nullable=True),
    )
    gpa_scale: Decimal | None = Field(
        default=None,
        sa_column=Column(Numeric(5, 2), nullable=True),
    )
    ielts_overall: Decimal | None = Field(
        default=None,
        sa_column=Column(Numeric(2, 1), nullable=True),
    )
    work_experience_years: Decimal | None = Field(
        default=None,
        sa_column=Column(Numeric(4, 1), nullable=True),
    )
    experience_summary: str | None = Field(default=None, max_length=4000)
    budget_cny: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    target_regions: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(String(length=100)), nullable=False),
    )
    target_fields: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(String(length=100)), nullable=False),
    )
    career_goal: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    user: User = Relationship()


class ProfileFieldHistory(SQLModel, table=True):
    __tablename__ = "profile_field_history"
    __table_args__ = (
        CheckConstraint(
            "field_name IN ("
            "'undergraduate_university', 'undergraduate_major', "
            "'gpa_value', 'gpa_scale', 'ielts_overall', "
            "'work_experience_years', 'experience_summary', 'budget_cny', "
            "'target_regions', 'target_fields', 'career_goal'"
            ")",
            name="ck_profile_field_history_field_name",
        ),
        CheckConstraint(
            "source IN ('user_explicit', 'agent_extracted')",
            name="ck_profile_field_history_source",
        ),
        CheckConstraint(
            "verification_status IN ('unverified', 'user_confirmed')",
            name="ck_profile_field_history_verification_status",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_profile_field_history_confidence_range",
        ),
        Index(
            "ix_profile_field_history_profile_field_created",
            "user_profile_id",
            "field_name",
            "created_at",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_profile_id: uuid.UUID = Field(
        foreign_key="user_profile.id",
        ondelete="CASCADE",
        nullable=False,
    )
    field_name: ProfileFieldName = Field(
        sa_column=enum_column(ProfileFieldName, length=64)
    )
    old_value: Any | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    new_value: Any | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    source: ProfileFieldSource = Field(
        sa_column=enum_column(ProfileFieldSource, length=32)
    )
    confidence: Decimal = Field(sa_column=Column(Numeric(4, 3), nullable=False))
    verification_status: ProfileVerificationStatus = Field(
        sa_column=enum_column(ProfileVerificationStatus, length=32)
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    user_profile: UserProfile = Relationship()
