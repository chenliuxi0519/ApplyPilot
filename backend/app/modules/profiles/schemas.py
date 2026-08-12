import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import StringConstraints, model_validator
from sqlmodel import Field, SQLModel

from app.modules.profiles.models import (
    ProfileFieldName,
    ProfileFieldSource,
    ProfileVerificationStatus,
)

ProfileTarget = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


class UserProfileUpdate(SQLModel):
    undergraduate_university: str | None = Field(default=None, max_length=255)
    undergraduate_major: str | None = Field(default=None, max_length=255)
    gpa_value: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    gpa_scale: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    ielts_overall: Decimal | None = Field(
        default=None,
        ge=0,
        le=9,
        decimal_places=1,
    )
    work_experience_years: Decimal | None = Field(
        default=None,
        ge=0,
        le=60,
        decimal_places=1,
    )
    experience_summary: str | None = Field(default=None, max_length=4000)
    budget_cny: int | None = Field(default=None, ge=0)
    target_regions: list[ProfileTarget] | None = Field(default=None, max_length=20)
    target_fields: list[ProfileTarget] | None = Field(default=None, max_length=20)
    career_goal: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_patch(self) -> "UserProfileUpdate":
        if not self.model_fields_set:
            raise ValueError("至少需要提供一个档案字段")

        gpa_fields = {"gpa_value", "gpa_scale"}
        if gpa_fields.issubset(self.model_fields_set):
            if (self.gpa_value is None) != (self.gpa_scale is None):
                raise ValueError("GPA 和 GPA 满分必须同时填写")
            if (
                self.gpa_value is not None
                and self.gpa_scale is not None
                and self.gpa_value > self.gpa_scale
            ):
                raise ValueError("GPA 不能超过 GPA 满分")
        return self


class UserProfilePublic(SQLModel):
    id: uuid.UUID
    user_id: uuid.UUID
    undergraduate_university: str | None
    undergraduate_major: str | None
    gpa_value: Decimal | None
    gpa_scale: Decimal | None
    ielts_overall: Decimal | None
    work_experience_years: Decimal | None
    experience_summary: str | None
    budget_cny: int | None
    target_regions: list[str]
    target_fields: list[str]
    career_goal: str | None
    created_at: datetime
    updated_at: datetime


class ProfileFieldHistoryPublic(SQLModel):
    id: uuid.UUID
    user_profile_id: uuid.UUID
    field_name: ProfileFieldName
    old_value: Any | None
    new_value: Any | None
    source: ProfileFieldSource
    confidence: Decimal
    verification_status: ProfileVerificationStatus
    created_at: datetime
