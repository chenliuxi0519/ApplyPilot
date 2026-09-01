import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlmodel import Session, col, select

from app.evaluation.case import EffectCheck, EffectKind
from app.modules.applications.models import Application, ApplicationTask
from app.modules.preferences import PreferenceStatus, UserPreference
from app.modules.profiles.models import UserProfile

Fingerprint = tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class EffectResult:
    check: EffectCheck
    passed: bool
    detail: str

    @property
    def label(self) -> str:
        return self.check.describe()


def fingerprint(session: Session, user_id: uuid.UUID) -> Fingerprint:
    session.expire_all()
    rows: list[tuple[str, ...]] = []

    profile = session.exec(
        select(UserProfile).where(col(UserProfile.user_id) == user_id)
    ).one_or_none()
    if profile is not None:
        rows.append(("profile", str(profile.id), profile.updated_at.isoformat()))

    preferences = session.exec(
        select(UserPreference).where(col(UserPreference.user_id) == user_id)
    ).all()
    for preference in sorted(preferences, key=lambda row: str(row.id)):
        rows.append(
            (
                "preference",
                str(preference.id),
                preference.preference_key,
                preference.value,
                preference.status.value,
            )
        )

    applications = session.exec(
        select(Application).where(col(Application.user_id) == user_id)
    ).all()
    for application in sorted(applications, key=lambda row: str(row.id)):
        rows.append(
            (
                "application",
                str(application.id),
                application.status.value,
                str(application.version),
            )
        )
        tasks = session.exec(
            select(ApplicationTask).where(
                col(ApplicationTask.application_id) == application.id
            )
        ).all()
        for task in sorted(tasks, key=lambda row: str(row.id)):
            rows.append(
                (
                    "task",
                    str(task.id),
                    task.task_type.value,
                    task.status.value,
                    str(task.version),
                )
            )
    return tuple(rows)


def check_effect(
    check: EffectCheck,
    *,
    session: Session,
    user_id: uuid.UUID,
    before: Fingerprint,
) -> EffectResult:
    if check.kind is EffectKind.NO_CHANGE:
        return _no_change(check, session, user_id, before)
    if check.kind is EffectKind.APPLICATION_COUNT:
        return _application_count(check, session, user_id)
    if check.kind is EffectKind.APPLICATION_STATUS:
        return _application_status(check, session, user_id)
    if check.kind is EffectKind.TASK_STATUS:
        return _task_status(check, session, user_id)
    if check.kind is EffectKind.PREFERENCE_VALUE:
        return _preference_value(check, session, user_id)
    return _profile_field(check, session, user_id)


def _no_change(
    check: EffectCheck, session: Session, user_id: uuid.UUID, before: Fingerprint
) -> EffectResult:
    after = fingerprint(session, user_id)
    if after == before:
        return EffectResult(check=check, passed=True, detail="数据未发生变化")
    added = [row for row in after if row not in before]
    removed = [row for row in before if row not in after]
    return EffectResult(
        check=check,
        passed=False,
        detail=f"changed: +{added} -{removed}",
    )


def _applications(session: Session, user_id: uuid.UUID) -> list[Application]:
    session.expire_all()
    return list(
        session.exec(
            select(Application).where(col(Application.user_id) == user_id)
        ).all()
    )


def _application_count(
    check: EffectCheck, session: Session, user_id: uuid.UUID
) -> EffectResult:
    expected = int(check.params["count"])
    actual = len(_applications(session, user_id))
    return EffectResult(
        check=check,
        passed=actual == expected,
        detail=f"expected {expected}, found {actual}",
    )


def _application_status(
    check: EffectCheck, session: Session, user_id: uuid.UUID
) -> EffectResult:
    expected = str(check.params["status"])
    applications = _applications(session, user_id)
    statuses = sorted(application.status.value for application in applications)
    return EffectResult(
        check=check,
        passed=statuses == [expected],
        detail=f"expected exactly one application in {expected}, found {statuses}",
    )


def _task_status(
    check: EffectCheck, session: Session, user_id: uuid.UUID
) -> EffectResult:
    task_type = str(check.params["task_type"])
    expected = str(check.params["status"])
    session.expire_all()
    found: list[str] = []
    for application in _applications(session, user_id):
        tasks = session.exec(
            select(ApplicationTask).where(
                col(ApplicationTask.application_id) == application.id
            )
        ).all()
        found.extend(
            task.status.value for task in tasks if task.task_type.value == task_type
        )
    return EffectResult(
        check=check,
        passed=found == [expected],
        detail=f"expected exactly one {task_type} task in {expected}, found {found}",
    )


def _profile_field(
    check: EffectCheck, session: Session, user_id: uuid.UUID
) -> EffectResult:
    field = str(check.params["field"])
    expected = str(check.params["value"])
    session.expire_all()
    profile = session.exec(
        select(UserProfile).where(col(UserProfile.user_id) == user_id)
    ).one_or_none()
    if profile is None:
        return EffectResult(check=check, passed=False, detail="个人档案不存在")
    actual = getattr(profile, field, None)
    rendered = _render(actual)
    return EffectResult(
        check=check,
        passed=rendered == expected,
        detail=f"{field}: expected {expected!r}, found {rendered!r}",
    )


def _preference_value(
    check: EffectCheck, session: Session, user_id: uuid.UUID
) -> EffectResult:
    key = str(check.params["key"])
    expected = str(check.params["value"])
    session.expire_all()
    row = session.exec(
        select(UserPreference).where(
            col(UserPreference.user_id) == user_id,
            col(UserPreference.preference_key) == key,
            col(UserPreference.status) == PreferenceStatus.ACTIVE,
        )
    ).one_or_none()
    actual = "" if row is None else row.value
    return EffectResult(
        check=check,
        passed=actual == expected,
        detail=f"{key}: expected {expected!r}, found {actual!r}",
    )


def _render(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def describe(results: Mapping[str, EffectResult]) -> str:
    return "; ".join(
        f"{name}: {result.detail}"
        for name, result in results.items()
        if not result.passed
    )
