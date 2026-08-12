import pytest

from app.modules.applications.models import ApplicationStatus, TaskStatus, TaskType
from app.modules.applications.state_machine import (
    ALLOWED_TRANSITIONS,
    BASE_TASK_TEMPLATE,
    HighRiskAction,
    high_risk_action,
    is_submitted,
    is_task_reopen,
    is_transition_allowed,
)

LEGAL = [
    (ApplicationStatus.SHORTLISTED, ApplicationStatus.PREPARING),
    (ApplicationStatus.PREPARING, ApplicationStatus.SHORTLISTED),
    (ApplicationStatus.PREPARING, ApplicationStatus.READY_TO_SUBMIT),
    (ApplicationStatus.READY_TO_SUBMIT, ApplicationStatus.PREPARING),
    (ApplicationStatus.READY_TO_SUBMIT, ApplicationStatus.SUBMITTED),
    (ApplicationStatus.SUBMITTED, ApplicationStatus.RESULT_PENDING),
    (ApplicationStatus.SUBMITTED, ApplicationStatus.OFFERED),
    (ApplicationStatus.SUBMITTED, ApplicationStatus.REJECTED),
    (ApplicationStatus.RESULT_PENDING, ApplicationStatus.OFFERED),
    (ApplicationStatus.RESULT_PENDING, ApplicationStatus.REJECTED),
    (ApplicationStatus.OFFERED, ApplicationStatus.WITHDRAWN),
    (ApplicationStatus.WITHDRAWN, ApplicationStatus.SHORTLISTED),
]

ILLEGAL = [
    (ApplicationStatus.SHORTLISTED, ApplicationStatus.READY_TO_SUBMIT),
    (ApplicationStatus.SHORTLISTED, ApplicationStatus.SUBMITTED),
    (ApplicationStatus.PREPARING, ApplicationStatus.SUBMITTED),
    (ApplicationStatus.READY_TO_SUBMIT, ApplicationStatus.OFFERED),
    (ApplicationStatus.READY_TO_SUBMIT, ApplicationStatus.RESULT_PENDING),
    (ApplicationStatus.SUBMITTED, ApplicationStatus.PREPARING),
    (ApplicationStatus.SUBMITTED, ApplicationStatus.READY_TO_SUBMIT),
    (ApplicationStatus.RESULT_PENDING, ApplicationStatus.SUBMITTED),
    (ApplicationStatus.REJECTED, ApplicationStatus.OFFERED),
    (ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN),
    (ApplicationStatus.OFFERED, ApplicationStatus.REJECTED),
    (ApplicationStatus.WITHDRAWN, ApplicationStatus.SUBMITTED),
]


@pytest.mark.parametrize(("current", "target"), LEGAL)
def test_allowed_transitions(
    current: ApplicationStatus, target: ApplicationStatus
) -> None:
    assert is_transition_allowed(current, target)


@pytest.mark.parametrize(("current", "target"), ILLEGAL)
def test_rejected_transitions(
    current: ApplicationStatus, target: ApplicationStatus
) -> None:
    assert not is_transition_allowed(current, target)


def test_every_status_has_a_transition_entry() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(ApplicationStatus)


def test_rejected_is_terminal() -> None:
    assert ALLOWED_TRANSITIONS[ApplicationStatus.REJECTED] == frozenset()


def test_withdraw_is_reachable_from_every_live_status() -> None:
    live = set(ApplicationStatus) - {
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.REJECTED,
    }
    for status in live:
        assert ApplicationStatus.WITHDRAWN in ALLOWED_TRANSITIONS[status]


def test_high_risk_actions() -> None:
    assert (
        high_risk_action(ApplicationStatus.SUBMITTED) is HighRiskAction.MARK_SUBMITTED
    )
    assert (
        high_risk_action(ApplicationStatus.WITHDRAWN)
        is HighRiskAction.WITHDRAW_APPLICATION
    )
    assert high_risk_action(ApplicationStatus.PREPARING) is None
    assert high_risk_action(ApplicationStatus.OFFERED) is None


def test_submitted_statuses() -> None:
    assert is_submitted(ApplicationStatus.SUBMITTED)
    assert is_submitted(ApplicationStatus.OFFERED)
    assert not is_submitted(ApplicationStatus.READY_TO_SUBMIT)
    assert not is_submitted(ApplicationStatus.WITHDRAWN)


def test_task_reopen_detection() -> None:
    assert is_task_reopen(TaskStatus.DONE, TaskStatus.TODO)
    assert is_task_reopen(TaskStatus.DONE, TaskStatus.BLOCKED)
    assert not is_task_reopen(TaskStatus.TODO, TaskStatus.DONE)
    assert not is_task_reopen(TaskStatus.DONE, TaskStatus.DONE)


def test_recommendation_is_optional_without_a_verified_requirement() -> None:
    recommendation = next(
        entry
        for entry in BASE_TASK_TEMPLATE
        if entry.task_type is TaskType.RECOMMENDATION
    )
    assert recommendation.is_required is False
