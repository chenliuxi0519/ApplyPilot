import uuid
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlmodel import Session, select

from app.models import User
from app.modules.profiles.models import (
    ProfileFieldHistory,
    ProfileFieldName,
    ProfileFieldSource,
    ProfileVerificationStatus,
    UserProfile,
    get_datetime_utc,
)
from app.modules.profiles.schemas import UserProfileUpdate

PROFILE_FIELDS = tuple(field.value for field in ProfileFieldName)
LIST_FIELDS = {"target_regions", "target_fields"}


class ProfileNotFoundError(LookupError):
    pass


class ProfileUserNotFoundError(LookupError):
    pass


class ProfileValidationError(ValueError):
    pass


def get_profile(*, session: Session, user_id: uuid.UUID) -> UserProfile | None:
    statement = select(UserProfile).where(UserProfile.user_id == user_id)
    return session.exec(statement).one_or_none()


def get_profile_or_raise(*, session: Session, user_id: uuid.UUID) -> UserProfile:
    profile = get_profile(session=session, user_id=user_id)
    if profile is None:
        raise ProfileNotFoundError("个人档案不存在")
    return profile


def update_profile(
    *,
    session: Session,
    user_id: uuid.UUID,
    profile_update: UserProfileUpdate,
    source: ProfileFieldSource,
    confidence: Decimal,
    verification_status: ProfileVerificationStatus,
) -> UserProfile:
    confidence = Decimal(str(confidence))
    if confidence < 0 or confidence > 1:
        raise ProfileValidationError("confidence must be between 0 and 1")

    try:
        user_statement = select(User).where(User.id == user_id).with_for_update()
        user = session.exec(user_statement).one_or_none()
        if user is None:
            raise ProfileUserNotFoundError("用户不存在")

        profile = get_profile(session=session, user_id=user_id)
        is_new = profile is None
        if profile is None:
            profile = UserProfile(user_id=user_id)

        update_data = _normalize_update(profile_update.model_dump(exclude_unset=True))
        effective_data = {
            field_name: update_data.get(field_name, getattr(profile, field_name))
            for field_name in PROFILE_FIELDS
        }
        _validate_effective_profile(effective_data)

        changes: list[tuple[ProfileFieldName, Any, Any]] = []
        for field_name, new_value in update_data.items():
            old_value = None if is_new else getattr(profile, field_name)
            if is_new or old_value != new_value:
                setattr(profile, field_name, new_value)
                changes.append((ProfileFieldName(field_name), old_value, new_value))

        if changes:
            profile.updated_at = get_datetime_utc()
            session.add(profile)
            session.flush()
            for field_name, old_value, new_value in changes:
                session.add(
                    ProfileFieldHistory(
                        user_profile_id=profile.id,
                        field_name=field_name,
                        old_value=_to_json_value(old_value),
                        new_value=_to_json_value(new_value),
                        source=source,
                        confidence=confidence,
                        verification_status=verification_status,
                    )
                )

        session.commit()
        session.refresh(profile)
        return profile
    except Exception:
        session.rollback()
        raise


def _normalize_update(update_data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(update_data)
    for field_name in LIST_FIELDS.intersection(normalized):
        values = normalized[field_name]
        normalized[field_name] = [] if values is None else _deduplicate(values)
    return normalized


def _deduplicate(values: list[str]) -> list[str]:
    unique_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized_value = value.strip()
        if normalized_value not in seen:
            unique_values.append(normalized_value)
            seen.add(normalized_value)
    return unique_values


def _validate_effective_profile(profile_data: dict[str, Any]) -> None:
    gpa_value = profile_data[ProfileFieldName.GPA_VALUE]
    gpa_scale = profile_data[ProfileFieldName.GPA_SCALE]
    if (gpa_value is None) != (gpa_scale is None):
        raise ProfileValidationError(
            "gpa_value and gpa_scale must both be set or both be null"
        )
    if gpa_value is not None and gpa_scale is not None:
        if gpa_value < 0:
            raise ProfileValidationError("gpa_value must not be negative")
        if gpa_scale <= 0:
            raise ProfileValidationError("gpa_scale must be greater than zero")
        if gpa_value > gpa_scale:
            raise ProfileValidationError("gpa_value must not exceed gpa_scale")

    budget_cny = profile_data[ProfileFieldName.BUDGET_CNY]
    if budget_cny is not None and budget_cny < 0:
        raise ProfileValidationError("budget_cny must not be negative")

    ielts_overall = profile_data[ProfileFieldName.IELTS_OVERALL]
    if ielts_overall is not None and not Decimal("0") <= ielts_overall <= Decimal("9"):
        raise ProfileValidationError("ielts_overall must be between 0 and 9")

    work_experience_years = profile_data[ProfileFieldName.WORK_EXPERIENCE_YEARS]
    if work_experience_years is not None and not Decimal(
        "0"
    ) <= work_experience_years <= Decimal("60"):
        raise ProfileValidationError("work_experience_years must be between 0 and 60")


def _to_json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, list):
        return [_to_json_value(item) for item in value]
    return value
