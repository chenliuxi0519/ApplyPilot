"""根据登录身份和调用内容决定直接执行、等待确认或拒绝。"""

from dataclasses import dataclass
from enum import StrEnum

from app.harness.models import ExecutionContext, PermissionLevel, ToolCall


class PolicyOutcome(StrEnum):
    ALLOW = "allow"
    REQUIRE_HUMAN_CONFIRMATION = "require_human_confirmation"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    permission_level: PermissionLevel
    reason: str


def decide(*, context: ExecutionContext, call: ToolCall) -> PolicyDecision:
    level = call.definition.effective_permission(call.payload)

    if level is PermissionLevel.READ:
        return PolicyDecision(PolicyOutcome.ALLOW, level, "只读操作可直接执行")

    if level is PermissionLevel.LOW_RISK_WRITE:
        return PolicyDecision(PolicyOutcome.ALLOW, level, "低风险修改可直接执行")

    if level is PermissionLevel.HIGH_RISK_WRITE:
        if context.is_approved(call.call_id):
            return PolicyDecision(PolicyOutcome.ALLOW, level, "用户已确认本次操作")
        return PolicyDecision(
            PolicyOutcome.REQUIRE_HUMAN_CONFIRMATION,
            level,
            "高风险修改需要用户确认",
        )

    if context.is_superuser:
        return PolicyDecision(PolicyOutcome.ALLOW, level, "管理员可执行此操作")
    return PolicyDecision(
        PolicyOutcome.DENY,
        level,
        "只有管理员可以执行此操作",
    )
