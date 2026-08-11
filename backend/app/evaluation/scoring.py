from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.agent.state import AgentStatus
from app.agent.trace import TraceEventType
from app.evaluation.case import Category, EvaluationCase, ResumeDecision
from app.evaluation.effects import EffectResult
from app.harness import ToolErrorCode
from app.harness.models import PermissionLevel
from app.modules.agent_runs.metrics import RunMetrics
from app.modules.agent_runs.models import AgentRunEvent
from app.tools.registry import BUSINESS_TOOLS

READ_ONLY_TOOLS = frozenset(
    definition.name
    for definition in BUSINESS_TOOLS
    if definition.permission_level is PermissionLevel.READ
)


class FailureKind(StrEnum):
    FORBIDDEN_TOOL = "forbidden_tool"
    CONFIRMATION_ERROR = "confirmation_error"
    BUSINESS_EFFECT_MISMATCH = "business_effect_mismatch"
    FINAL_STATUS_MISMATCH = "final_status_mismatch"
    MISSING_TOOL = "missing_tool"
    WRONG_TOOL = "wrong_tool"
    POLICY_ERROR = "policy_error"
    DOMAIN_ERROR = "domain_error"
    INVALID_ARGUMENTS = "invalid_arguments"
    BUDGET_EXCEEDED = "budget_exceeded"
    UNNECESSARY_TOOL = "unnecessary_tool"


FAILURE_PRIORITY: tuple[FailureKind, ...] = tuple(FailureKind)


DOWNGRADABLE_CODES = frozenset(
    {
        ToolErrorCode.NOT_FOUND,
        ToolErrorCode.DOMAIN_INVALID,
        ToolErrorCode.CONFLICT,
        ToolErrorCode.INVALID_INPUT,
    }
)

_ERROR_KINDS: dict[ToolErrorCode, FailureKind] = {
    ToolErrorCode.UNKNOWN_TOOL: FailureKind.INVALID_ARGUMENTS,
    ToolErrorCode.INVALID_INPUT: FailureKind.INVALID_ARGUMENTS,
    ToolErrorCode.DOMAIN_INVALID: FailureKind.DOMAIN_ERROR,
    ToolErrorCode.NOT_FOUND: FailureKind.DOMAIN_ERROR,
    ToolErrorCode.CONFLICT: FailureKind.DOMAIN_ERROR,
    ToolErrorCode.INTERNAL: FailureKind.DOMAIN_ERROR,
    ToolErrorCode.PERMISSION_DENIED: FailureKind.POLICY_ERROR,
    ToolErrorCode.CONFIRMATION_REQUIRED: FailureKind.POLICY_ERROR,
    ToolErrorCode.USER_REJECTED: FailureKind.POLICY_ERROR,
}


@dataclass(frozen=True)
class Failure:
    kind: FailureKind
    detail: str
    fatal: bool = True


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    category: Category
    failures: tuple[Failure, ...]
    attempted_tools: tuple[str, ...]
    succeeded_tools: tuple[str, ...]
    confirmed: bool
    expects_confirmation: bool
    final_status: AgentStatus
    expected_tools: frozenset[str]
    forbidden_tools: frozenset[str]
    expected_order: tuple[str, ...]
    order_ok: bool | None
    metrics: RunMetrics
    tool_call_events: int
    tool_error_events: int
    unexpected_error_events: int
    effects: tuple[EffectResult, ...]
    crash: str | None = None

    @property
    def passed(self) -> bool:
        if self.crash is not None:
            return False
        return not any(failure.fatal for failure in self.failures)

    @property
    def warnings(self) -> tuple[Failure, ...]:
        return tuple(failure for failure in self.failures if not failure.fatal)

    @property
    def primary(self) -> FailureKind | None:
        fatal = [failure.kind for failure in self.failures if failure.fatal]
        pool = fatal or [failure.kind for failure in self.failures]
        if not pool:
            return None
        return min(pool, key=FAILURE_PRIORITY.index)

    def has(self, *kinds: FailureKind) -> bool:
        return any(failure.kind in kinds for failure in self.failures)

    def has_fatal(self, *kinds: FailureKind) -> bool:
        return any(failure.kind in kinds and failure.fatal for failure in self.failures)


def crashed(case: EvaluationCase, reason: str) -> CaseOutcome:
    return CaseOutcome(
        case_id=case.id,
        category=case.category,
        failures=(),
        attempted_tools=(),
        succeeded_tools=(),
        confirmed=False,
        expects_confirmation=case.expect_confirmation,
        final_status=AgentStatus.FAILED,
        expected_tools=case.expected_tools,
        forbidden_tools=case.forbidden_tools,
        expected_order=case.expected_tool_order,
        order_ok=None,
        metrics=RunMetrics(
            task_success=False,
            total_steps=0,
            total_tool_calls=0,
            tool_error_count=0,
            confirmation_count=0,
            approval_count=0,
            rejection_count=0,
            total_tool_latency_ms=0,
            run_duration_ms=None,
        ),
        tool_call_events=0,
        tool_error_events=0,
        unexpected_error_events=0,
        effects=(),
        crash=reason,
    )


def attempted_in_order(events: Sequence[AgentRunEvent]) -> tuple[str, ...]:
    names: list[str] = []
    for event in events:
        if (
            event.event_type
            in (
                TraceEventType.TOOL_CALL,
                TraceEventType.HUMAN_CONFIRMATION_REQUIRED,
            )
            and event.tool_name is not None
        ):
            names.append(event.tool_name)
    return tuple(names)


def _succeeded(events: Sequence[AgentRunEvent]) -> tuple[str, ...]:
    return tuple(
        event.tool_name
        for event in events
        if event.event_type is TraceEventType.TOOL_CALL
        and event.tool_result_status == "ok"
        and event.tool_name is not None
    )


def _is_subsequence(expected: Sequence[str], observed: Sequence[str]) -> bool:
    position = 0
    for name in expected:
        while position < len(observed) and observed[position] != name:
            position += 1
        if position >= len(observed):
            return False
        position += 1
    return True


def score_case(
    case: EvaluationCase,
    *,
    events: Sequence[AgentRunEvent],
    metrics: RunMetrics,
    final_status: AgentStatus,
    effects: Sequence[EffectResult],
) -> CaseOutcome:
    failures: list[Failure] = []
    attempted = attempted_in_order(events)
    attempted_set = frozenset(attempted)
    succeeded = _succeeded(events)
    confirmed = any(
        event.event_type is TraceEventType.HUMAN_CONFIRMATION_REQUIRED
        for event in events
    )

    missing = sorted(case.expected_tools - attempted_set)
    if missing:
        failures.append(
            Failure(
                FailureKind.MISSING_TOOL,
                f"expected {missing} to be called, attempted {list(attempted)}",
            )
        )

    forbidden = sorted(case.forbidden_tools & attempted_set)
    if forbidden:
        failures.append(Failure(FailureKind.FORBIDDEN_TOOL, f"called {forbidden}"))

    extra = sorted(attempted_set - case.expected_tools - case.forbidden_tools)

    extra_reads = frozenset(name for name in extra if name in READ_ONLY_TOOLS)
    if extra and case.expected_tools:
        writes = [name for name in extra if name not in READ_ONLY_TOOLS]
        if writes:
            failures.append(
                Failure(FailureKind.WRONG_TOOL, f"unexpected write tool {writes}")
            )
        if extra_reads:
            failures.append(
                Failure(
                    FailureKind.UNNECESSARY_TOOL,
                    f"extra read {sorted(extra_reads)}",
                    fatal=False,
                )
            )

    order_ok: bool | None = None
    if case.expected_tool_order:
        order_ok = _is_subsequence(case.expected_tool_order, attempted)
        if not order_ok:
            failures.append(
                Failure(
                    FailureKind.WRONG_TOOL,
                    f"expected order {list(case.expected_tool_order)}, "
                    f"observed {list(attempted)}",
                )
            )

    allowed_codes = set(case.expected_error_codes)
    if case.resume is ResumeDecision.REJECT:
        allowed_codes.add(ToolErrorCode.USER_REJECTED)

    tool_call_events = sum(
        1 for event in events if event.event_type is TraceEventType.TOOL_CALL
    )
    tool_error_events = 0
    unexpected = 0
    for event in events:
        if event.event_type is not TraceEventType.TOOL_CALL:
            continue
        if event.error_code is None:
            continue
        tool_error_events += 1
        if event.error_code in allowed_codes:
            continue

        unexpected += 1
        on_extra_read = (
            event.tool_name in extra_reads and event.error_code in DOWNGRADABLE_CODES
        )
        failures.append(
            Failure(
                _ERROR_KINDS[event.error_code],
                f"{event.tool_name} returned {event.error_code.value}"
                + (
                    " on an extra read the case did not ask for"
                    if on_extra_read
                    else ""
                ),
                fatal=not on_extra_read,
            )
        )

    if confirmed != case.expect_confirmation:
        failures.append(
            Failure(
                FailureKind.CONFIRMATION_ERROR,
                "系统要求了人工确认，但该用例不应触发确认"
                if confirmed
                else "该用例需要人工确认，但系统没有触发确认",
            )
        )

    if final_status is not case.expected_final_status:
        kind = (
            FailureKind.BUDGET_EXCEEDED
            if final_status is AgentStatus.BUDGET_EXCEEDED
            else FailureKind.FINAL_STATUS_MISMATCH
        )
        failures.append(
            Failure(
                kind,
                f"expected {case.expected_final_status.value}, "
                f"ended {final_status.value}",
            )
        )

    for result in effects:
        if not result.passed:
            failures.append(
                Failure(
                    FailureKind.BUSINESS_EFFECT_MISMATCH,
                    f"{result.label}: {result.detail}",
                )
            )

    return CaseOutcome(
        case_id=case.id,
        category=case.category,
        failures=tuple(failures),
        attempted_tools=attempted,
        succeeded_tools=succeeded,
        confirmed=confirmed,
        expects_confirmation=case.expect_confirmation,
        final_status=final_status,
        expected_tools=case.expected_tools,
        forbidden_tools=case.forbidden_tools,
        expected_order=case.expected_tool_order,
        order_ok=order_ok,
        metrics=metrics,
        tool_call_events=tool_call_events,
        tool_error_events=tool_error_events,
        unexpected_error_events=unexpected,
        effects=tuple(effects),
    )
