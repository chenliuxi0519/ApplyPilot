"""申请状态、风险动作和默认材料任务的确定性规则。"""

from dataclasses import dataclass
from enum import StrEnum

from app.modules.applications.models import (
    SUBMITTED_STATUSES,
    ApplicationStatus,
    TaskSource,
    TaskStatus,
    TaskType,
)
from app.modules.programs.models import RequirementFieldName

ALLOWED_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    ApplicationStatus.SHORTLISTED: frozenset(
        {ApplicationStatus.PREPARING, ApplicationStatus.WITHDRAWN}
    ),
    ApplicationStatus.PREPARING: frozenset(
        {
            ApplicationStatus.SHORTLISTED,
            ApplicationStatus.READY_TO_SUBMIT,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.READY_TO_SUBMIT: frozenset(
        {
            ApplicationStatus.PREPARING,
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.SUBMITTED: frozenset(
        {
            ApplicationStatus.RESULT_PENDING,
            ApplicationStatus.OFFERED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.RESULT_PENDING: frozenset(
        {
            ApplicationStatus.OFFERED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.OFFERED: frozenset({ApplicationStatus.WITHDRAWN}),
    ApplicationStatus.REJECTED: frozenset(),
    # 撤回后只能回到选校清单，不能直接跳回准备或提交阶段。
    ApplicationStatus.WITHDRAWN: frozenset({ApplicationStatus.SHORTLISTED}),
}


class HighRiskAction(StrEnum):
    MARK_SUBMITTED = "mark_submitted"
    WITHDRAW_APPLICATION = "withdraw_application"
    DELETE_APPLICATION = "delete_application"


HIGH_RISK_TRANSITIONS: dict[ApplicationStatus, HighRiskAction] = {
    ApplicationStatus.SUBMITTED: HighRiskAction.MARK_SUBMITTED,
    ApplicationStatus.WITHDRAWN: HighRiskAction.WITHDRAW_APPLICATION,
}

ACTION_EFFECTS: dict[HighRiskAction, tuple[str, ...]] = {
    HighRiskAction.MARK_SUBMITTED: (
        "申请将被记录为已提交。",
        "必要材料任务将不能重新打开。",
    ),
    HighRiskAction.WITHDRAW_APPLICATION: ("申请将被撤回，并移出当前申请计划。",),
    HighRiskAction.DELETE_APPLICATION: ("申请及其全部任务将被永久删除。",),
}


@dataclass(frozen=True)
class TaskTemplateEntry:
    task_type: TaskType
    title: str

    is_required: bool
    source: TaskSource = TaskSource.TEMPLATE


BASE_TASK_TEMPLATE: tuple[TaskTemplateEntry, ...] = (
    TaskTemplateEntry(TaskType.CV, "准备个人简历", is_required=True),
    TaskTemplateEntry(TaskType.PERSONAL_STATEMENT, "撰写个人陈述", is_required=True),
    TaskTemplateEntry(TaskType.TRANSCRIPT, "准备成绩单", is_required=True),
    TaskTemplateEntry(TaskType.APPLICATION_FORM, "填写申请表", is_required=True),
    TaskTemplateEntry(TaskType.RECOMMENDATION, "准备推荐信", is_required=False),
)


LANGUAGE_REQUIREMENT_FIELDS: tuple[RequirementFieldName, ...] = (
    RequirementFieldName.IELTS_OVERALL,
    RequirementFieldName.IELTS_MIN_BAND,
    RequirementFieldName.TOEFL_OVERALL,
)

LANGUAGE_TASK_TITLE = "提交语言成绩"
LANGUAGE_TASK_TITLE_UNVERIFIED = "提交语言成绩（要求尚未核实）"


def is_transition_allowed(
    current: ApplicationStatus, target: ApplicationStatus
) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def high_risk_action(target: ApplicationStatus) -> HighRiskAction | None:
    return HIGH_RISK_TRANSITIONS.get(target)


def effects_of(action: HighRiskAction) -> list[str]:
    return list(ACTION_EFFECTS[action])


def is_submitted(status: ApplicationStatus) -> bool:
    return status in SUBMITTED_STATUSES


def is_task_reopen(current: TaskStatus, target: TaskStatus) -> bool:
    return current is TaskStatus.DONE and target is not TaskStatus.DONE
