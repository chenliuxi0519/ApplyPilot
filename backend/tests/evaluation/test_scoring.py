import dataclasses
import uuid

import pytest

from app.agent.state import AgentStatus
from app.agent.trace import TraceEventType
from app.evaluation.case import (
    NO_CHANGE,
    Category,
    EffectCheck,
    EffectKind,
    EvaluationCase,
    ResumeDecision,
)
from app.evaluation.effects import EffectResult
from app.evaluation.scoring import (
    FailureKind,
    attempted_in_order,
    score_case,
)
from app.harness import PolicyOutcome, ToolErrorCode
from app.modules.agent_runs.metrics import RunMetrics
from app.modules.agent_runs.models import AgentRunEvent

RUN_ID = uuid.uuid4()


def _event(
    sequence: int,
    event_type: TraceEventType,
    *,
    tool_name: str | None = None,
    status: str | None = None,
    error_code: ToolErrorCode | None = None,
    latency_ms: int = 5,
) -> AgentRunEvent:
    return AgentRunEvent(
        run_id=RUN_ID,
        sequence=sequence,
        step=1,
        event_type=event_type,
        latency_ms=latency_ms,
        tool_name=tool_name,
        tool_call_id=None if tool_name is None else f"toolu_{sequence}",
        policy_outcome=None if tool_name is None else PolicyOutcome.ALLOW,
        tool_result_status=status,  # type: ignore[arg-type]
        error_code=error_code,
    )


def _tool(
    sequence: int, name: str, *, ok: bool = True, code: ToolErrorCode | None = None
):
    return _event(
        sequence,
        TraceEventType.TOOL_CALL,
        tool_name=name,
        status="ok" if ok else "error",
        error_code=code,
    )


def _metrics() -> RunMetrics:
    return RunMetrics(
        task_success=True,
        total_steps=2,
        total_tool_calls=1,
        tool_error_count=0,
        confirmation_count=0,
        approval_count=0,
        rejection_count=0,
        total_tool_latency_ms=5,
        run_duration_ms=20,
    )


def _case(**kwargs: object) -> EvaluationCase:
    base = EvaluationCase(
        id="t_001",
        category=Category.APPLICATION,
        user_message="x",
        setup="empty",
        script="read_profile",
    )
    return dataclasses.replace(base, **kwargs)  # type: ignore[arg-type]


def _score(case: EvaluationCase, events, *, status=AgentStatus.COMPLETED, effects=()):
    return score_case(
        case,
        events=events,
        metrics=_metrics(),
        final_status=status,
        effects=list(effects),
    )


def _ok(check=NO_CHANGE) -> EffectResult:
    return EffectResult(check=check, passed=True, detail="unchanged")


def _bad(check=NO_CHANGE) -> EffectResult:
    return EffectResult(check=check, passed=False, detail="changed")


def test_a_paused_call_counts_as_attempted_even_though_it_never_ran() -> None:
    events = [
        _event(
            0,
            TraceEventType.HUMAN_CONFIRMATION_REQUIRED,
            tool_name="update_application_status",
        )
    ]
    assert attempted_in_order(events) == ("update_application_status",)


def test_a_denied_or_rejected_call_still_counts_as_a_routing_decision() -> None:
    events = [_tool(0, "create_application", ok=False, code=ToolErrorCode.CONFLICT)]
    assert attempted_in_order(events) == ("create_application",)


def test_a_matching_run_produces_no_failures() -> None:
    case = _case(expected_tools=frozenset({"get_user_profile"}))
    outcome = _score(case, [_tool(0, "get_user_profile")], effects=[_ok()])
    assert outcome.failures == ()
    assert outcome.passed


def test_a_missing_tool_is_caught() -> None:
    case = _case(expected_tools=frozenset({"get_user_profile"}))
    outcome = _score(case, [_tool(0, "search_programs")])
    assert outcome.has(FailureKind.MISSING_TOOL)
    assert not outcome.passed


def test_an_extra_read_is_noted_but_does_not_fail_the_case() -> None:
    case = _case(expected_tools=frozenset({"search_programs"}))
    outcome = _score(case, [_tool(0, "search_programs"), _tool(1, "get_user_profile")])
    assert outcome.has(FailureKind.UNNECESSARY_TOOL)
    assert outcome.passed


#


def test_an_extra_read_that_finds_nothing_does_not_fail_the_case() -> None:
    case = _case(expected_tools=frozenset({"update_application_status"}))
    outcome = _score(
        case,
        [
            _tool(0, "get_user_profile", ok=False, code=ToolErrorCode.NOT_FOUND),
            _tool(1, "update_application_status"),
        ],
        effects=[_ok()],
    )
    assert outcome.passed
    assert outcome.has(FailureKind.DOMAIN_ERROR)
    assert not outcome.has_fatal(FailureKind.DOMAIN_ERROR)


def test_the_forgiven_error_still_counts_towards_the_error_rates() -> None:
    case = _case(expected_tools=frozenset({"update_application_status"}))
    outcome = _score(
        case,
        [
            _tool(0, "get_user_profile", ok=False, code=ToolErrorCode.NOT_FOUND),
            _tool(1, "update_application_status"),
        ],
        effects=[_ok()],
    )
    assert outcome.tool_error_events == 1
    assert outcome.unexpected_error_events == 1


def test_a_forgiven_error_is_reported_as_a_warning_not_hidden() -> None:
    case = _case(expected_tools=frozenset({"update_application_status"}))
    outcome = _score(
        case,
        [
            _tool(
                0, "get_program_requirements", ok=False, code=ToolErrorCode.NOT_FOUND
            ),
            _tool(1, "update_application_status"),
        ],
        effects=[_ok()],
    )
    kinds = {failure.kind for failure in outcome.warnings}
    assert FailureKind.DOMAIN_ERROR in kinds
    assert any("get_program_requirements" in f.detail for f in outcome.warnings)


@pytest.mark.parametrize(
    "code",
    [
        ToolErrorCode.NOT_FOUND,
        ToolErrorCode.DOMAIN_INVALID,
        ToolErrorCode.CONFLICT,
        ToolErrorCode.INVALID_INPUT,
    ],
)
def test_every_domain_answer_to_an_extra_read_is_forgiven(
    code: ToolErrorCode,
) -> None:
    case = _case(expected_tools=frozenset({"update_application_status"}))
    outcome = _score(
        case,
        [
            _tool(0, "get_user_profile", ok=False, code=code),
            _tool(1, "update_application_status"),
        ],
        effects=[_ok()],
    )
    assert outcome.passed, code


def test_a_denial_on_an_extra_read_is_still_fatal() -> None:
    case = _case(expected_tools=frozenset({"update_application_status"}))
    outcome = _score(
        case,
        [
            _tool(
                0, "get_user_profile", ok=False, code=ToolErrorCode.PERMISSION_DENIED
            ),
            _tool(1, "update_application_status"),
        ],
        effects=[_ok()],
    )
    assert not outcome.passed
    assert outcome.has_fatal(FailureKind.POLICY_ERROR)


def test_an_error_from_an_expected_tool_is_still_fatal() -> None:
    case = _case(expected_tools=frozenset({"get_user_profile"}))
    outcome = _score(
        case,
        [_tool(0, "get_user_profile", ok=False, code=ToolErrorCode.NOT_FOUND)],
        effects=[_ok()],
    )
    assert not outcome.passed
    assert outcome.has_fatal(FailureKind.DOMAIN_ERROR)


def test_an_error_from_an_extra_write_is_still_fatal() -> None:
    case = _case(expected_tools=frozenset({"search_programs"}))
    outcome = _score(
        case,
        [
            _tool(0, "search_programs"),
            _tool(1, "create_application", ok=False, code=ToolErrorCode.CONFLICT),
        ],
        effects=[_ok()],
    )
    assert not outcome.passed
    assert outcome.has_fatal(FailureKind.WRONG_TOOL)
    assert outcome.has_fatal(FailureKind.DOMAIN_ERROR)


def test_a_forbidden_read_is_still_fatal_however_it_ends() -> None:
    case = _case(
        expected_tools=frozenset({"search_programs"}),
        forbidden_tools=frozenset({"get_user_profile"}),
    )
    outcome = _score(
        case,
        [
            _tool(0, "search_programs"),
            _tool(1, "get_user_profile", ok=False, code=ToolErrorCode.NOT_FOUND),
        ],
        effects=[_ok()],
    )
    assert not outcome.passed
    assert outcome.has_fatal(FailureKind.FORBIDDEN_TOOL)
    assert outcome.has_fatal(FailureKind.DOMAIN_ERROR)
    assert outcome.primary is FailureKind.FORBIDDEN_TOOL


def test_a_wrong_business_effect_fails_even_alongside_a_forgiven_read() -> None:
    case = _case(expected_tools=frozenset({"update_application_status"}))
    outcome = _score(
        case,
        [
            _tool(0, "get_user_profile", ok=False, code=ToolErrorCode.NOT_FOUND),
            _tool(1, "update_application_status"),
        ],
        effects=[_bad()],
    )
    assert not outcome.passed
    assert outcome.has_fatal(FailureKind.BUSINESS_EFFECT_MISMATCH)


def test_a_wrong_final_status_fails_even_alongside_a_forgiven_read() -> None:
    case = _case(expected_tools=frozenset({"update_application_status"}))
    outcome = _score(
        case,
        [
            _tool(0, "get_user_profile", ok=False, code=ToolErrorCode.NOT_FOUND),
            _tool(1, "update_application_status"),
        ],
        status=AgentStatus.FAILED,
        effects=[_ok()],
    )
    assert not outcome.passed
    assert outcome.has_fatal(FailureKind.FINAL_STATUS_MISMATCH)


def test_a_forgiven_read_does_not_lift_the_harness_accuracy_figure() -> None:
    from app.evaluation.aggregate import deterministic_metrics

    case = _case(expected_tools=frozenset({"update_application_status"}))
    outcome = _score(
        case,
        [
            _tool(0, "get_user_profile", ok=False, code=ToolErrorCode.NOT_FOUND),
            _tool(1, "update_application_status"),
        ],
        effects=[_ok()],
    )
    metrics = deterministic_metrics([outcome])
    assert metrics.harness_execution_accuracy.value == 1.0
    assert metrics.common.unexpected_tool_error_rate.numerator == 1


def test_an_extra_write_fails_the_case() -> None:
    case = _case(expected_tools=frozenset({"search_programs"}))
    outcome = _score(
        case, [_tool(0, "search_programs"), _tool(1, "create_application")]
    )
    assert outcome.has(FailureKind.WRONG_TOOL)
    assert not outcome.passed


def test_a_forbidden_tool_is_its_own_failure_and_outranks_everything() -> None:
    case = _case(
        expected_tools=frozenset({"search_programs"}),
        forbidden_tools=frozenset({"update_user_profile"}),
    )
    outcome = _score(
        case,
        [_tool(0, "search_programs"), _tool(1, "update_user_profile")],
        status=AgentStatus.FAILED,
    )
    assert outcome.has(FailureKind.FORBIDDEN_TOOL)
    assert outcome.primary is FailureKind.FORBIDDEN_TOOL


def test_order_is_a_subsequence_not_an_exact_match() -> None:
    case = _case(
        expected_tools=frozenset({"get_user_profile", "get_program_requirements"}),
        expected_tool_order=("get_user_profile", "get_program_requirements"),
    )
    outcome = _score(
        case,
        [
            _tool(0, "get_user_profile"),
            _tool(1, "search_programs"),
            _tool(2, "get_program_requirements"),
        ],
    )
    assert outcome.order_ok is True


def test_a_reversed_order_fails() -> None:
    case = _case(
        expected_tools=frozenset({"get_user_profile", "get_program_requirements"}),
        expected_tool_order=("get_user_profile", "get_program_requirements"),
    )
    outcome = _score(
        case,
        [_tool(0, "get_program_requirements"), _tool(1, "get_user_profile")],
    )
    assert outcome.order_ok is False
    assert outcome.has(FailureKind.WRONG_TOOL)


def test_an_expected_error_is_not_a_failure() -> None:
    case = _case(
        expected_tools=frozenset({"create_application"}),
        expected_error_codes=frozenset({ToolErrorCode.CONFLICT}),
    )
    outcome = _score(
        case, [_tool(0, "create_application", ok=False, code=ToolErrorCode.CONFLICT)]
    )
    assert outcome.passed
    assert outcome.tool_error_events == 1
    assert outcome.unexpected_error_events == 0


def test_an_unexpected_error_is_classified_by_its_code() -> None:
    case = _case(expected_tools=frozenset({"create_application"}))
    outcome = _score(
        case, [_tool(0, "create_application", ok=False, code=ToolErrorCode.CONFLICT)]
    )
    assert outcome.has(FailureKind.DOMAIN_ERROR)
    assert outcome.unexpected_error_events == 1


def test_invalid_input_is_an_argument_failure() -> None:
    case = _case(expected_tools=frozenset({"create_application"}))
    outcome = _score(
        case,
        [_tool(0, "create_application", ok=False, code=ToolErrorCode.INVALID_INPUT)],
    )
    assert outcome.has(FailureKind.INVALID_ARGUMENTS)


def test_a_denial_is_a_policy_failure() -> None:
    case = _case(expected_tools=frozenset({"create_application"}))
    outcome = _score(
        case,
        [
            _tool(
                0, "create_application", ok=False, code=ToolErrorCode.PERMISSION_DENIED
            )
        ],
    )
    assert outcome.has(FailureKind.POLICY_ERROR)


def test_a_declined_call_is_expected_on_a_reject_case() -> None:
    case = _case(
        expected_tools=frozenset({"update_application_status"}),
        expect_confirmation=True,
        resume=ResumeDecision.REJECT,
    )
    events = [
        _event(
            0,
            TraceEventType.HUMAN_CONFIRMATION_REQUIRED,
            tool_name="update_application_status",
        ),
        _tool(
            1,
            "update_application_status",
            ok=False,
            code=ToolErrorCode.USER_REJECTED,
        ),
    ]
    outcome = _score(case, events, effects=[_ok()])
    assert outcome.passed
    assert outcome.unexpected_error_events == 0


def test_a_missing_confirmation_is_caught() -> None:
    case = _case(
        expected_tools=frozenset({"update_application_status"}),
        expect_confirmation=True,
    )
    outcome = _score(case, [_tool(0, "update_application_status")])
    assert outcome.has(FailureKind.CONFIRMATION_ERROR)


def test_an_unexpected_confirmation_is_also_caught() -> None:
    case = _case(expected_tools=frozenset({"update_application_status"}))
    outcome = _score(
        case,
        [
            _event(
                0,
                TraceEventType.HUMAN_CONFIRMATION_REQUIRED,
                tool_name="update_application_status",
            )
        ],
        status=AgentStatus.WAITING_CONFIRMATION,
    )
    assert outcome.has(FailureKind.CONFIRMATION_ERROR)


def test_a_wrong_final_status_is_caught() -> None:
    outcome = _score(_case(), [], status=AgentStatus.FAILED)
    assert outcome.has(FailureKind.FINAL_STATUS_MISMATCH)


def test_an_unexpected_budget_stop_is_its_own_kind() -> None:
    outcome = _score(_case(), [], status=AgentStatus.BUDGET_EXCEEDED)
    assert outcome.has(FailureKind.BUDGET_EXCEEDED)
    assert not outcome.has(FailureKind.FINAL_STATUS_MISMATCH)


def test_an_expected_budget_stop_is_fine() -> None:
    case = _case(expected_final_status=AgentStatus.BUDGET_EXCEEDED)
    outcome = _score(case, [], status=AgentStatus.BUDGET_EXCEEDED, effects=[_ok()])
    assert outcome.passed


def test_a_business_effect_mismatch_fails_even_when_routing_was_perfect() -> None:
    case = _case(
        expected_tools=frozenset({"create_application"}),
        expected_effect=EffectCheck(
            kind=EffectKind.APPLICATION_COUNT, params={"count": 1}
        ),
    )
    outcome = _score(case, [_tool(0, "create_application")], effects=[_bad()])
    assert outcome.has(FailureKind.BUSINESS_EFFECT_MISMATCH)
    assert not outcome.passed


def test_priority_puts_safety_before_efficiency() -> None:
    case = _case(
        expected_tools=frozenset({"search_programs"}),
        forbidden_tools=frozenset({"update_user_profile"}),
    )
    outcome = _score(
        case,
        [
            _tool(0, "search_programs"),
            _tool(1, "get_user_profile"),
            _tool(2, "update_user_profile"),
        ],
        effects=[_bad()],
    )
    assert outcome.primary is FailureKind.FORBIDDEN_TOOL
