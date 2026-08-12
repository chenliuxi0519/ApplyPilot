from collections.abc import Sequence
from dataclasses import dataclass

from app.evaluation.case import Category
from app.evaluation.scoring import CaseOutcome, FailureKind


@dataclass(frozen=True)
class Ratio:
    numerator: int
    denominator: int

    @property
    def value(self) -> float | None:
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator

    def render(self) -> str:
        if self.denominator == 0:
            return "n/a"
        return f"{self.value:>7.1%}   ({self.numerator}/{self.denominator})"


def _ratio(passed: int, total: int) -> Ratio:
    return Ratio(numerator=passed, denominator=total)


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


@dataclass(frozen=True)
class CommonMetrics:
    business_effect_accuracy: Ratio
    tool_error_rate: Ratio
    unexpected_tool_error_rate: Ratio
    mean_steps: float | None
    mean_tool_calls: float | None
    mean_tool_latency_ms: float | None


@dataclass(frozen=True)
class DeterministicMetrics:
    cases: int
    passed: int
    case_pass_rate: Ratio
    harness_execution_accuracy: Ratio
    policy_decision_accuracy: Ratio
    hitl_behavior_accuracy: Ratio
    hitl_precision: Ratio
    hitl_recall: Ratio
    final_status_accuracy: Ratio
    error_recovery_success: Ratio
    common: CommonMetrics


@dataclass(frozen=True)
class RealMetrics:
    cases: int
    passed: int
    task_success_rate: Ratio
    tool_selection_accuracy: Ratio
    forbidden_tool_rate: Ratio
    tool_sequence_accuracy: Ratio
    hitl_precision: Ratio
    hitl_recall: Ratio
    common: CommonMetrics


_HARNESS_KINDS = (
    FailureKind.MISSING_TOOL,
    FailureKind.WRONG_TOOL,
    FailureKind.FORBIDDEN_TOOL,
    FailureKind.INVALID_ARGUMENTS,
    FailureKind.DOMAIN_ERROR,
    FailureKind.POLICY_ERROR,
)


def _common(outcomes: Sequence[CaseOutcome]) -> CommonMetrics:
    effects = [result for outcome in outcomes for result in outcome.effects]
    tool_calls = sum(outcome.tool_call_events for outcome in outcomes)
    latency = sum(outcome.metrics.total_tool_latency_ms for outcome in outcomes)
    ran = [outcome for outcome in outcomes if outcome.crash is None]
    return CommonMetrics(
        business_effect_accuracy=_ratio(
            sum(1 for result in effects if result.passed), len(effects)
        ),
        tool_error_rate=_ratio(
            sum(outcome.tool_error_events for outcome in outcomes), tool_calls
        ),
        unexpected_tool_error_rate=_ratio(
            sum(outcome.unexpected_error_events for outcome in outcomes), tool_calls
        ),
        mean_steps=_mean([outcome.metrics.total_steps for outcome in ran]),
        mean_tool_calls=_mean([outcome.metrics.total_tool_calls for outcome in ran]),
        mean_tool_latency_ms=None if tool_calls == 0 else latency / tool_calls,
    )


def _hitl(outcomes: Sequence[CaseOutcome]) -> tuple[Ratio, Ratio]:
    confirmed = [outcome for outcome in outcomes if outcome.confirmed]
    should = [outcome for outcome in outcomes if outcome.expects_confirmation]
    correct = sum(1 for outcome in confirmed if outcome.expects_confirmation)
    recalled = sum(1 for outcome in should if outcome.confirmed)
    return _ratio(correct, len(confirmed)), _ratio(recalled, len(should))


def deterministic_metrics(outcomes: Sequence[CaseOutcome]) -> DeterministicMetrics:
    total = len(outcomes)
    passed = sum(1 for outcome in outcomes if outcome.passed)
    precision, recall = _hitl(outcomes)
    recovery = [
        outcome for outcome in outcomes if outcome.category is Category.ERROR_RECOVERY
    ]
    return DeterministicMetrics(
        cases=total,
        passed=passed,
        case_pass_rate=_ratio(passed, total),
        harness_execution_accuracy=_ratio(
            sum(1 for outcome in outcomes if not outcome.has_fatal(*_HARNESS_KINDS)),
            total,
        ),
        policy_decision_accuracy=_ratio(
            sum(
                1
                for outcome in outcomes
                if not outcome.has_fatal(
                    FailureKind.POLICY_ERROR, FailureKind.CONFIRMATION_ERROR
                )
            ),
            total,
        ),
        hitl_behavior_accuracy=_ratio(
            sum(
                1
                for outcome in outcomes
                if not outcome.has_fatal(FailureKind.CONFIRMATION_ERROR)
            ),
            total,
        ),
        hitl_precision=precision,
        hitl_recall=recall,
        final_status_accuracy=_ratio(
            sum(
                1
                for outcome in outcomes
                if not outcome.has_fatal(
                    FailureKind.FINAL_STATUS_MISMATCH, FailureKind.BUDGET_EXCEEDED
                )
            ),
            total,
        ),
        error_recovery_success=_ratio(
            sum(1 for outcome in recovery if outcome.passed), len(recovery)
        ),
        common=_common(outcomes),
    )


def real_metrics(outcomes: Sequence[CaseOutcome]) -> RealMetrics:
    total = len(outcomes)
    passed = sum(1 for outcome in outcomes if outcome.passed)
    precision, recall = _hitl(outcomes)

    expected_total = sum(len(outcome.expected_tools) for outcome in outcomes)
    expected_hit = sum(
        len(outcome.expected_tools & frozenset(outcome.attempted_tools))
        for outcome in outcomes
    )
    ordered = [outcome for outcome in outcomes if outcome.order_ok is not None]
    with_forbidden = [outcome for outcome in outcomes if outcome.forbidden_tools]
    return RealMetrics(
        cases=total,
        passed=passed,
        task_success_rate=_ratio(passed, total),
        tool_selection_accuracy=_ratio(expected_hit, expected_total),
        forbidden_tool_rate=_ratio(
            sum(
                1
                for outcome in with_forbidden
                if outcome.has_fatal(FailureKind.FORBIDDEN_TOOL)
            ),
            len(with_forbidden),
        ),
        tool_sequence_accuracy=_ratio(
            sum(1 for outcome in ordered if outcome.order_ok), len(ordered)
        ),
        hitl_precision=precision,
        hitl_recall=recall,
        common=_common(outcomes),
    )
