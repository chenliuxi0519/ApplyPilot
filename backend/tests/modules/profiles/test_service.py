import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import cast

import pytest
from sqlalchemy.exc import IntegrityError, StatementError
from sqlmodel import Session, select

from app.core.db import engine
from app.modules.profiles.models import (
    ProfileFieldHistory,
    ProfileFieldName,
    ProfileFieldSource,
    ProfileVerificationStatus,
    UserProfile,
)
from app.modules.profiles.schemas import UserProfileUpdate
from app.modules.profiles.service import ProfileValidationError, update_profile
from tests.utils.user import create_random_user


def test_update_profile_creates_profile_and_confirmed_history(db: Session) -> None:
    user = create_random_user(db)
    profile = update_profile(
        session=db,
        user_id=user.id,
        profile_update=UserProfileUpdate(
            undergraduate_university="NUS",
            target_regions=["Singapore", "Singapore"],
        ),
        source=ProfileFieldSource.USER_EXPLICIT,
        confidence=Decimal("1.000"),
        verification_status=ProfileVerificationStatus.USER_CONFIRMED,
    )

    history = db.exec(
        select(ProfileFieldHistory).where(
            ProfileFieldHistory.user_profile_id == profile.id
        )
    ).all()
    assert profile.target_regions == ["Singapore"]
    assert {row.field_name.value for row in history} == {
        "undergraduate_university",
        "target_regions",
    }
    assert all(row.source == ProfileFieldSource.USER_EXPLICIT for row in history)
    assert all(
        row.verification_status == ProfileVerificationStatus.USER_CONFIRMED
        for row in history
    )
    assert all(row.confidence == Decimal("1.000") for row in history)


def test_update_profile_validates_effective_gpa(db: Session) -> None:
    user = create_random_user(db)
    with pytest.raises(ProfileValidationError):
        update_profile(
            session=db,
            user_id=user.id,
            profile_update=UserProfileUpdate(gpa_value=Decimal("3.5")),
            source=ProfileFieldSource.USER_EXPLICIT,
            confidence=Decimal("1"),
            verification_status=ProfileVerificationStatus.USER_CONFIRMED,
        )
    assert (
        db.exec(select(UserProfile).where(UserProfile.user_id == user.id)).one_or_none()
        is None
    )


def test_database_rejects_negative_budget(db: Session) -> None:
    user = create_random_user(db)
    db.add(UserProfile(user_id=user.id, budget_cny=-1))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_rejects_gpa_above_scale(db: Session) -> None:
    user = create_random_user(db)
    db.add(
        UserProfile(
            user_id=user.id,
            gpa_value=Decimal("4.1"),
            gpa_scale=Decimal("4.0"),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_rejects_ielts_above_nine(db: Session) -> None:
    user = create_random_user(db)
    db.add(UserProfile(user_id=user.id, ielts_overall=Decimal("9.1")))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_enforces_unique_user_profile(db: Session) -> None:
    user = create_random_user(db)
    db.add(UserProfile(user_id=user.id))
    db.commit()
    db.add(UserProfile(user_id=user.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_enforces_user_foreign_key(db: Session) -> None:
    db.add(UserProfile(user_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_enforces_confidence_range(db: Session) -> None:
    user = create_random_user(db)
    profile = UserProfile(user_id=user.id)
    db.add(profile)
    db.commit()
    db.add(
        ProfileFieldHistory(
            user_profile_id=profile.id,
            field_name=ProfileFieldName.CAREER_GOAL,
            old_value=None,
            new_value="AI engineer",
            source=ProfileFieldSource.USER_EXPLICIT,
            confidence=Decimal("1.001"),
            verification_status=ProfileVerificationStatus.USER_CONFIRMED,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_deleting_user_cascades_profile_and_history(db: Session) -> None:
    user = create_random_user(db)
    profile = update_profile(
        session=db,
        user_id=user.id,
        profile_update=UserProfileUpdate(career_goal="AI engineer"),
        source=ProfileFieldSource.USER_EXPLICIT,
        confidence=Decimal("1.000"),
        verification_status=ProfileVerificationStatus.USER_CONFIRMED,
    )
    profile_id = profile.id
    db.delete(user)
    db.commit()
    assert db.get(UserProfile, profile_id) is None
    assert (
        db.exec(
            select(ProfileFieldHistory).where(
                ProfileFieldHistory.user_profile_id == profile_id
            )
        ).all()
        == []
    )


def test_history_failure_rolls_back_new_profile(db: Session) -> None:
    user = create_random_user(db)
    with pytest.raises(StatementError):
        update_profile(
            session=db,
            user_id=user.id,
            profile_update=UserProfileUpdate(career_goal="AI engineer"),
            source=cast(ProfileFieldSource, "invalid_source"),
            confidence=Decimal("1.000"),
            verification_status=ProfileVerificationStatus.USER_CONFIRMED,
        )
    assert (
        db.exec(select(UserProfile).where(UserProfile.user_id == user.id)).one_or_none()
        is None
    )


def test_concurrent_first_updates_create_one_profile(db: Session) -> None:
    user = create_random_user(db)
    user_id = user.id

    def patch(update: UserProfileUpdate) -> None:
        with Session(engine) as session:
            update_profile(
                session=session,
                user_id=user_id,
                profile_update=update,
                source=ProfileFieldSource.USER_EXPLICIT,
                confidence=Decimal("1.000"),
                verification_status=ProfileVerificationStatus.USER_CONFIRMED,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(patch, UserProfileUpdate(undergraduate_university="NUS")),
            executor.submit(patch, UserProfileUpdate(career_goal="AI engineer")),
        ]
        for future in futures:
            future.result()

    db.expire_all()
    profiles = db.exec(select(UserProfile).where(UserProfile.user_id == user_id)).all()
    assert len(profiles) == 1
    assert profiles[0].undergraduate_university == "NUS"
    assert profiles[0].career_goal == "AI engineer"
