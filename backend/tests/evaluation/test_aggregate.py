from app.agent.state import AgentStatus
from app.evaluation.aggregate import deterministic_metrics, real_metrics
from app.evaluation.case import NO_CHANGE, Category
from app.evaluation.effects import EffectResult
from app.evaluation.scoring import CaseOutcome, Failure, FailureKind
from app.modules.agent_runs.metrics import RunMetrics


def _metrics(steps: int = 2, tool_calls: int = 1, latency: int = 10) -> RunMetrics:
    return RunMetrics(
        task_success=True,
        total_steps=steps,
        total_tool_calls=tool_calls,
        tool_error_count=0,
        confirmation_count=0,
        approval_count=0,
        rejection_count=0,
        total_tool_latency_ms=latency,
        run_duration_ms=30,
    )


def _outcome(
    case_id: str,
    *,
    category: Category = Category.APPLICATION,
    failures: tuple[Failure, ...] = (),
    confirmed: bool = False,
    expects_confirmation: bool = False,
    expected_tools: frozenset[str] = frozenset(),
    forbidden_tools: frozenset[str] = frozenset(),
    attempted: tuple[str, ...] = (),
    order_ok: bool | None = None,
    effects: tuple[EffectResult, ...] = (),
    tool_call_events: int = 1,
    tool_error_events: int = 0,
    unexpected: int = 0,
    steps: int = 2,
    tool_calls: int = 1,
    latency: int = 10,
) -> CaseOutcome:
    return CaseOutcome(
        case_id=case_id,
        category=category,
        failures=failures,
        attempted_tools=attempted,
        succeeded_tools=attempted,
        confirmed=confirmed,
        expects_confirmation=expects_confirmation,
        final_status=AgentStatus.COMPLETED,
        expected_tools=expected_tools,
        forbidden_tools=forbidden_tools,
        expected_order=(),
        order_ok=order_ok,
        metrics=_metrics(steps, tool_calls, latency),
        tool_call_events=tool_call_events,
        tool_error_events=tool_error_events,
        unexpected_error_events=unexpected,
        effects=effects,
    )


def _passed(check=NO_CHANGE) -> EffectResult:
    return EffectResult(check=check, passed=True, detail="ok")


def _failed(check=NO_CHANGE) -> EffectResult:
    return EffectResult(check=check, passed=False, detail="no")


def test_deterministic_metrics_on_a_clean_sweep() -> None:
    outcomes = [
        _outcome("a", effects=(_passed(),)),
        _outcome("b", effects=(_passed(),)),
    ]
    metrics = deterministic_metrics(outcomes)

    assert metrics.cases == 2
    assert metrics.passed == 2
    assert metrics.case_pass_rate.value == 1.0
    assert metrics.common.clean_pass_rate.value == 1.0
    assert metrics.common.warning_case_rate.value == 0.0
    assert metrics.harness_execution_accuracy.value == 1.0
    assert metrics.common.business_effect_accuracy.value == 1.0
    assert metrics.common.mean_steps == 2.0
    assert metrics.common.mean_tool_calls == 1.0
    assert metrics.common.mean_tool_latency_ms == 10.0


def test_a_harness_failure_lowers_only_the_harness_figure() -> None:
    outcomes = [
        _outcome("a", effects=(_passed(),)),
        _outcome(
            "b",
            failures=(Failure(FailureKind.MISSING_TOOL, "x"),),
            effects=(_passed(),),
        ),
    ]
    metrics = deterministic_metrics(outcomes)
    assert metrics.harness_execution_accuracy.value == 0.5
    assert metrics.hitl_behavior_accuracy.value == 1.0
    assert metrics.final_status_accuracy.value == 1.0


def test_an_extra_read_does_not_lower_the_pass_rate() -> None:
    outcomes = [
        _outcome(
            "a",
            failures=(Failure(FailureKind.UNNECESSARY_TOOL, "extra", fatal=False),),
            effects=(_passed(),),
        )
    ]
    metrics = deterministic_metrics(outcomes)
    assert metrics.case_pass_rate.value == 1.0
    assert metrics.common.clean_pass_rate.value == 0.0
    assert metrics.common.warning_case_rate.value == 1.0
    assert metrics.common.unnecessary_tool_case_rate.value == 1.0


def test_a_non_fatal_observation_does_not_lower_any_accuracy_figure() -> None:
    outcomes = [
        _outcome(
            "a",
            failures=(Failure(FailureKind.DOMAIN_ERROR, "extra read", fatal=False),),
            effects=(_passed(),),
        )
    ]
    metrics = deterministic_metrics(outcomes)
    assert metrics.case_pass_rate.value == 1.0
    assert metrics.harness_execution_accuracy.value == 1.0


def test_hitl_precision_and_recall_are_computed_from_both_directions() -> None:
    outcomes = [
        _outcome("a", confirmed=True, expects_confirmation=True),
        _outcome("b", confirmed=True, expects_confirmation=False),
        _outcome("c", confirmed=False, expects_confirmation=True),
        _outcome("d"),
    ]
    metrics = deterministic_metrics(outcomes)
    assert metrics.hitl_precision.numerator == 1
    assert metrics.hitl_precision.denominator == 2
    assert metrics.hitl_recall.numerator == 1
    assert metrics.hitl_recall.denominator == 2


def test_an_empty_denominator_renders_as_not_applicable() -> None:
    metrics = deterministic_metrics([_outcome("a")])
    assert metrics.hitl_precision.value is None
    assert metrics.hitl_precision.render() == "n/a"


def test_error_recovery_is_scored_over_its_own_category_only() -> None:
    outcomes = [
        _outcome("a", category=Category.ERROR_RECOVERY),
        _outcome(
            "b",
            category=Category.ERROR_RECOVERY,
            failures=(Failure(FailureKind.DOMAIN_ERROR, "x"),),
        ),
        _outcome("c", category=Category.PROFILE),
    ]
    metrics = deterministic_metrics(outcomes)
    assert metrics.error_recovery_success.numerator == 1
    assert metrics.error_recovery_success.denominator == 2


def test_expected_errors_show_in_the_error_rate_but_not_the_unexpected_one() -> None:
    outcomes = [_outcome("a", tool_call_events=4, tool_error_events=2, unexpected=0)]
    common = deterministic_metrics(outcomes).common
    assert common.tool_error_rate.numerator == 2
    assert common.tool_error_rate.denominator == 4
    assert common.unexpected_tool_error_rate.numerator == 0


def test_business_effect_accuracy_counts_every_check_not_every_case() -> None:
    outcomes = [_outcome("a", effects=(_passed(), _failed()))]
    common = deterministic_metrics(outcomes).common
    assert common.business_effect_accuracy.numerator == 1
    assert common.business_effect_accuracy.denominator == 2


def test_tool_selection_accuracy_is_micro_averaged() -> None:
    outcomes = [
        _outcome("a", expected_tools=frozenset({"x", "y"}), attempted=("x",)),
        _outcome("b", expected_tools=frozenset({"z"}), attempted=("z",)),
    ]
    metrics = real_metrics(outcomes)
    assert metrics.tool_selection_accuracy.numerator == 2
    assert metrics.tool_selection_accuracy.denominator == 3


def test_forbidden_tool_rate_only_counts_cases_that_declared_one() -> None:
    outcomes = [
        _outcome("a"),
        _outcome("b", forbidden_tools=frozenset({"x"})),
        _outcome(
            "c",
            forbidden_tools=frozenset({"x"}),
            failures=(Failure(FailureKind.FORBIDDEN_TOOL, "x"),),
        ),
    ]
    metrics = real_metrics(outcomes)
    assert metrics.forbidden_tool_rate.numerator == 1
    assert metrics.forbidden_tool_rate.denominator == 2


def test_sequence_accuracy_ignores_cases_without_a_required_order() -> None:
    outcomes = [
        _outcome("a"),
        _outcome("b", order_ok=True),
        _outcome("c", order_ok=False),
    ]
    metrics = real_metrics(outcomes)
    assert metrics.tool_sequence_accuracy.numerator == 1
    assert metrics.tool_sequence_accuracy.denominator == 2
