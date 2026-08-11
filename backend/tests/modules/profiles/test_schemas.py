from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.profiles.schemas import UserProfileUpdate


def test_profile_patch_requires_at_least_one_field() -> None:
    with pytest.raises(ValidationError):
        UserProfileUpdate()


def test_profile_patch_rejects_gpa_above_scale() -> None:
    with pytest.raises(ValidationError):
        UserProfileUpdate(gpa_value=Decimal("4.1"), gpa_scale=Decimal("4.0"))


def test_profile_patch_accepts_partial_non_gpa_update() -> None:
    update = UserProfileUpdate(target_regions=[" Singapore "])
    assert update.target_regions == ["Singapore"]


def test_profile_patch_validates_work_experience_range() -> None:
    with pytest.raises(ValidationError):
        UserProfileUpdate(work_experience_years=Decimal("60.1"))

    update = UserProfileUpdate(
        work_experience_years=Decimal("1.5"),
        experience_summary="Two internships and one research project",
    )
    assert update.work_experience_years == Decimal("1.5")
