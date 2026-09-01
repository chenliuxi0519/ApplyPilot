import json
from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from app.agent.prompt import SYSTEM_PROMPT
from app.core.config import settings
from app.evaluation.aggregate import (
    DeterministicMetrics,
    Ratio,
    RealMetrics,
    deterministic_metrics,
    real_metrics,
)
from app.evaluation.runner import Mode
from app.evaluation.scoring import CaseOutcome, FailureKind

WIDTH = 28


def _line(label: str, ratio: Ratio) -> str:
    return f"{label:<{WIDTH}}{ratio.render()}"


def _mean(label: str, value: float | None, suffix: str = "") -> str:
    rendered = "无数据" if value is None else f"{value:>7.1f}{suffix}"
    return f"{label:<{WIDTH}}{rendered}"


def _deterministic_body(metrics: DeterministicMetrics) -> list[str]:
    common = metrics.common
    return [
        "确定性运行评测",
        "工具调用由脚本提供，本评测只检查运行框架的校验、权限、暂停、执行和恢复。",
        "",
        f"用例：{metrics.cases}    通过：{metrics.passed}    "
        f"失败：{metrics.cases - metrics.passed}",
        "",
        _line("用例通过率", metrics.case_pass_rate),
        _line("无警告通过率", common.clean_pass_rate),
        _line("警告用例率", common.warning_case_rate),
        _line("冗余工具用例率", common.unnecessary_tool_case_rate),
        _line("工具执行准确率", metrics.harness_execution_accuracy),
        _line("权限判断准确率", metrics.policy_decision_accuracy),
        _line("人工确认行为准确率", metrics.hitl_behavior_accuracy),
        _line("  人工确认精确率", metrics.hitl_precision),
        _line("  人工确认召回率", metrics.hitl_recall),
        _line("业务结果准确率", common.business_effect_accuracy),
        _line("错误恢复成功率", metrics.error_recovery_success),
        _line("最终状态准确率", metrics.final_status_accuracy),
        _line("工具错误率", common.tool_error_rate),
        _line("  非预期错误", common.unexpected_tool_error_rate),
        _mean("平均步骤数", common.mean_steps),
        _mean("平均工具调用数", common.mean_tool_calls),
        _mean("平均工具耗时", common.mean_tool_latency_ms, "毫秒"),
        _mean("P95 步骤数", common.p95_steps),
        _mean("P95 工具调用数", common.p95_tool_calls),
        "",
        "耗时只统计工具执行；确定性模式不调用真实模型。",
    ]


def _real_body(metrics: RealMetrics) -> list[str]:
    common = metrics.common
    return [
        "真实模型评测",
        "工具由模型自行选择，以下指标反映模型表现。",
        "",
        f"用例：{metrics.cases}    通过：{metrics.passed}    "
        f"失败：{metrics.cases - metrics.passed}",
        "",
        _line("任务成功率", metrics.task_success_rate),
        _line("无警告通过率", common.clean_pass_rate),
        _line("警告用例率", common.warning_case_rate),
        _line("冗余工具用例率", common.unnecessary_tool_case_rate),
        _line("工具选择准确率", metrics.tool_selection_accuracy),
        _line("禁用工具调用率", metrics.forbidden_tool_rate),
        _line("工具顺序准确率", metrics.tool_sequence_accuracy),
        _line("人工确认精确率", metrics.hitl_precision),
        _line("人工确认召回率", metrics.hitl_recall),
        _line("业务结果准确率", common.business_effect_accuracy),
        _line("工具错误率", common.tool_error_rate),
        _line("  非预期错误", common.unexpected_tool_error_rate),
        _mean("平均步骤数", common.mean_steps),
        _mean("平均工具调用数", common.mean_tool_calls),
        _mean("平均工具耗时", common.mean_tool_latency_ms, "毫秒"),
        _mean("P95 步骤数", common.p95_steps),
        _mean("P95 工具调用数", common.p95_tool_calls),
    ]


def _failure_lines(outcomes: Sequence[CaseOutcome]) -> list[str]:
    lines: list[str] = []
    for outcome in outcomes:
        if outcome.passed:
            continue
        primary = outcome.primary
        head = primary.value if primary else "运行崩溃"
        lines.append("")
        lines.append(f"失败  {outcome.case_id:<38}{head}")
        if outcome.crash:
            lines.append(f"  异常：    {outcome.crash}")
            continue
        lines.append(f"  预期工具：{sorted(outcome.expected_tools) or '-'}")
        lines.append(f"  实际工具：{list(outcome.attempted_tools) or '-'}")
        for failure in outcome.failures:
            if not failure.fatal:
                continue
            lines.append(f"  原因：    {failure.kind.value}: {failure.detail}")
    return lines


def _warning_lines(outcomes: Sequence[CaseOutcome]) -> list[str]:
    lines: list[str] = []
    for outcome in outcomes:
        if not outcome.passed or not outcome.warnings:
            continue
        lines.append("")
        lines.append(f"通过  {outcome.case_id}")
        for failure in outcome.warnings:
            lines.append(f"  警告：    {failure.kind.value}: {failure.detail}")
    return lines


def _histogram(outcomes: Sequence[CaseOutcome]) -> list[str]:
    by_kind: dict[FailureKind, int] = {}
    by_category: dict[str, int] = {}
    for outcome in outcomes:
        if outcome.passed:
            continue
        primary = outcome.primary
        if primary is not None:
            by_kind[primary] = by_kind.get(primary, 0) + 1
        key = outcome.category.value
        by_category[key] = by_category.get(key, 0) + 1
    if not by_category:
        return []
    kinds = ", ".join(
        f"{kind.value} {count}"
        for kind, count in sorted(by_kind.items(), key=lambda item: -item[1])
    )
    categories = ", ".join(
        f"{name} {count}"
        for name, count in sorted(by_category.items(), key=lambda item: -item[1])
    )
    return [
        "",
        f"{'按类型统计失败':<{WIDTH}}{kinds or '-'}",
        f"{'按类别统计失败':<{WIDTH}}{categories}",
    ]


def render(outcomes: Sequence[CaseOutcome], *, mode: Mode) -> str:
    body = (
        _deterministic_body(deterministic_metrics(outcomes))
        if mode is Mode.DETERMINISTIC
        else _real_body(real_metrics(outcomes))
    )
    return "\n".join(
        [
            *body,
            *_failure_lines(outcomes),
            *_warning_lines(outcomes),
            *_histogram(outcomes),
        ]
    )


def to_json(outcomes: Sequence[CaseOutcome], *, mode: Mode) -> dict[str, object]:
    common = (
        deterministic_metrics(outcomes).common
        if mode is Mode.DETERMINISTIC
        else real_metrics(outcomes).common
    )
    return {
        "mode": mode.value,
        "metadata": {
            "runtime": "langgraph",
            "model": "scripted" if mode is Mode.DETERMINISTIC else settings.AGENT_MODEL,
            "prompt_hash": sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12],
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "summary": {
            "clean_pass_rate": common.clean_pass_rate.value,
            "warning_case_rate": common.warning_case_rate.value,
            "unnecessary_tool_case_rate": common.unnecessary_tool_case_rate.value,
            "mean_steps": common.mean_steps,
            "mean_tool_calls": common.mean_tool_calls,
            "p95_steps": common.p95_steps,
            "p95_tool_calls": common.p95_tool_calls,
        },
        "cases": [
            {
                "id": outcome.case_id,
                "category": outcome.category.value,
                "passed": outcome.passed,
                "primary_failure": None
                if outcome.primary is None
                else outcome.primary.value,
                "failures": [
                    {
                        "kind": failure.kind.value,
                        "detail": failure.detail,
                        "fatal": failure.fatal,
                    }
                    for failure in outcome.failures
                ],
                "attempted_tools": list(outcome.attempted_tools),
                "succeeded_tools": list(outcome.succeeded_tools),
                "confirmed": outcome.confirmed,
                "final_status": outcome.final_status.value,
                "steps": outcome.metrics.total_steps,
                "tool_calls": outcome.metrics.total_tool_calls,
                "tool_latency_ms": outcome.metrics.total_tool_latency_ms,
                "crash": outcome.crash,
            }
            for outcome in outcomes
        ],
    }


def write_json(outcomes: Sequence[CaseOutcome], *, mode: Mode, path: Path) -> None:
    path.write_text(
        json.dumps(to_json(outcomes, mode=mode), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
