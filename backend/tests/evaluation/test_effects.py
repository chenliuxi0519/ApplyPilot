from sqlmodel import Session

from app.evaluation.case import NO_CHANGE, EffectCheck, EffectKind
from app.evaluation.effects import check_effect, fingerprint
from app.modules.applications.models import ApplicationStatus, TaskStatus
from tests.utils.application import (
    complete_required_tasks,
    create_application_for,
    move_to,
)
from tests.utils.user import create_random_user


def _check(check: EffectCheck, db: Session, user_id, before=()):
    return check_effect(check, session=db, user_id=user_id, before=before)


def test_no_change_passes_when_nothing_happened(db: Session) -> None:
    user, _, _ = create_application_for(db)
    before = fingerprint(db, user.id)
    assert _check(NO_CHANGE, db, user.id, before).passed


def test_no_change_notices_a_status_move(db: Session) -> None:
    user, application, _ = create_application_for(db)
    before = fingerprint(db, user.id)
    move_to(db, user=user, application=application, target=ApplicationStatus.PREPARING)

    result = _check(NO_CHANGE, db, user.id, before)
    assert not result.passed
    assert "changed" in result.detail


def test_no_change_notices_a_task_edit(db: Session) -> None:
    user, application, _ = create_application_for(db)
    move_to(db, user=user, application=application, target=ApplicationStatus.PREPARING)
    before = fingerprint(db, user.id)
    complete_required_tasks(db, user=user, application_id=application.id)

    assert not _check(NO_CHANGE, db, user.id, before).passed


def test_application_count(db: Session) -> None:
    user, _, _ = create_application_for(db)
    check = EffectCheck(kind=EffectKind.APPLICATION_COUNT, params={"count": 1})
    assert _check(check, db, user.id).passed

    wrong = EffectCheck(kind=EffectKind.APPLICATION_COUNT, params={"count": 2})
    assert not _check(wrong, db, user.id).passed


def test_application_status(db: Session) -> None:
    user, application, _ = create_application_for(db)
    move_to(db, user=user, application=application, target=ApplicationStatus.PREPARING)

    good = EffectCheck(
        kind=EffectKind.APPLICATION_STATUS, params={"status": "preparing"}
    )
    bad = EffectCheck(
        kind=EffectKind.APPLICATION_STATUS, params={"status": "shortlisted"}
    )
    assert _check(good, db, user.id).passed
    assert not _check(bad, db, user.id).passed


def test_task_status(db: Session) -> None:
    user, application, _ = create_application_for(db)
    move_to(db, user=user, application=application, target=ApplicationStatus.PREPARING)
    complete_required_tasks(db, user=user, application_id=application.id)

    good = EffectCheck(
        kind=EffectKind.TASK_STATUS,
        params={"task_type": "cv", "status": TaskStatus.DONE.value},
    )
    bad = EffectCheck(
        kind=EffectKind.TASK_STATUS,
        params={"task_type": "cv", "status": TaskStatus.TODO.value},
    )
    assert _check(good, db, user.id).passed
    assert not _check(bad, db, user.id).passed


def test_profile_field(db: Session) -> None:
    from decimal import Decimal

    from app.modules.profiles import service as profile_service
    from app.modules.profiles.models import (
        ProfileFieldSource,
        ProfileVerificationStatus,
    )
    from app.modules.profiles.schemas import UserProfileUpdate

    user = create_random_user(db)
    profile_service.update_profile(
        session=db,
        user_id=user.id,
        profile_update=UserProfileUpdate(career_goal="ML engineer"),
        source=ProfileFieldSource.USER_EXPLICIT,
        verification_status=ProfileVerificationStatus.USER_CONFIRMED,
        confidence=Decimal("1.000"),
    )

    good = EffectCheck(
        kind=EffectKind.PROFILE_FIELD,
        params={"field": "career_goal", "value": "ML engineer"},
    )
    bad = EffectCheck(
        kind=EffectKind.PROFILE_FIELD,
        params={"field": "career_goal", "value": "something else"},
    )
    assert _check(good, db, user.id).passed
    assert not _check(bad, db, user.id).passed


def test_profile_field_on_a_user_without_a_profile(db: Session) -> None:
    user = create_random_user(db)
    check = EffectCheck(
        kind=EffectKind.PROFILE_FIELD, params={"field": "career_goal", "value": "x"}
    )
    result = _check(check, db, user.id)
    assert not result.passed
    assert "个人档案不存在" in result.detail


def test_a_list_field_renders_as_a_comma_separated_value(db: Session) -> None:
    from decimal import Decimal

    from app.modules.profiles import service as profile_service
    from app.modules.profiles.models import (
        ProfileFieldSource,
        ProfileVerificationStatus,
    )
    from app.modules.profiles.schemas import UserProfileUpdate

    user = create_random_user(db)
    profile_service.update_profile(
        session=db,
        user_id=user.id,
        profile_update=UserProfileUpdate(target_regions=["singapore", "hong_kong"]),
        source=ProfileFieldSource.USER_EXPLICIT,
        verification_status=ProfileVerificationStatus.USER_CONFIRMED,
        confidence=Decimal("1.000"),
    )
    check = EffectCheck(
        kind=EffectKind.PROFILE_FIELD,
        params={"field": "target_regions", "value": "singapore,hong_kong"},
    )
    assert _check(check, db, user.id).passed
