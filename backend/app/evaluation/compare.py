"""把两次评测摆在一起，回答"这次改动到底是不是正向的"。

单看总分回答不了这个问题：54 题从 50 变成 51，可能是修好一题，也可能是修好
三题又弄坏两题。所以这里逐用例对照，把修复和回归分开数，并且只有在一个回归
都没有的前提下才判定为改进。

数据集自己也会变。新增和删除的用例单独列出来，绝不并进修复或回归——把新加的
通过用例算成"修好了"是自欺欺人。

对照的前提是两次跑的是同一件事。模式不同（确定性 vs 真实模型）直接拒绝比较；
prompt 或模型换了则在抬头标出来，因为那正是"哪个变量动了"的答案。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WIDTH = 28

# 展示顺序：先看退步，再看进步，最后才是没动的部分。
_PERCENT_SUFFIX = "_rate"


class ReportFormatError(ValueError):
    pass


@dataclass(frozen=True)
class CaseRecord:
    case_id: str
    passed: bool
    primary_failure: str | None

    @property
    def label(self) -> str:
        if self.passed:
            return "通过"
        return self.primary_failure or "运行崩溃"


@dataclass(frozen=True)
class CaseDelta:
    case_id: str
    before: str
    after: str


@dataclass(frozen=True)
class MetricDelta:
    name: str
    before: float | None
    after: float | None

    @property
    def delta(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return self.after - self.before


@dataclass(frozen=True)
class Comparison:
    mode: str
    prompt_before: str
    prompt_after: str
    model_before: str
    model_after: str
    passed_before: int
    passed_after: int
    total_before: int
    total_after: int
    fixed: tuple[CaseDelta, ...]
    regressed: tuple[CaseDelta, ...]
    changed_failure: tuple[CaseDelta, ...]
    added: tuple[CaseDelta, ...]
    removed: tuple[CaseDelta, ...]
    metrics: tuple[MetricDelta, ...]

    @property
    def has_regression(self) -> bool:
        return bool(self.regressed)

    @property
    def prompt_changed(self) -> bool:
        return self.prompt_before != self.prompt_after

    @property
    def verdict(self) -> str:
        if self.regressed:
            return "回归：有用例从通过变成失败，这次改动不能算正向"
        if self.fixed:
            return "改进：有用例被修好，且没有任何用例退步"
        if self.changed_failure:
            return "存疑：没有用例翻面，但失败原因变了"
        if not self.prompt_changed and (self.added or self.removed):
            return "持平：prompt 没变，差异来自数据集增删"
        if not self.prompt_changed:
            return "持平：prompt 与结果都没有变化"
        return "持平：prompt 变了，但没有用例翻面"


def load_report(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ReportFormatError(f"无法读取评测报告 {path}：{error}") from error
    except json.JSONDecodeError as error:
        raise ReportFormatError(f"{path} 不是合法 JSON：{error}") from error
    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise ReportFormatError(f"{path} 不像评测报告：缺少 cases 列表")
    return raw


def _records(report: dict[str, Any]) -> dict[str, CaseRecord]:
    records: dict[str, CaseRecord] = {}
    for entry in report["cases"]:
        if not isinstance(entry, dict) or "id" not in entry:
            raise ReportFormatError("评测报告里有缺少 id 的用例条目")
        case_id = str(entry["id"])
        records[case_id] = CaseRecord(
            case_id=case_id,
            passed=bool(entry.get("passed")),
            primary_failure=entry.get("primary_failure"),
        )
    return records


def _meta(report: dict[str, Any], key: str) -> str:
    metadata = report.get("metadata")
    if not isinstance(metadata, dict):
        return "未知"
    return str(metadata.get(key, "未知"))


def _summary(report: dict[str, Any]) -> dict[str, float | None]:
    summary = report.get("summary")
    if not isinstance(summary, dict):
        return {}
    return {
        str(name): (float(value) if isinstance(value, int | float) else None)
        for name, value in summary.items()
    }


def compare(*, baseline: dict[str, Any], current: dict[str, Any]) -> Comparison:
    """逐用例对照两份报告。

    比较模式不同的两次运行没有意义：确定性模式的工具调用来自脚本，真实模式
    来自模型，两者的失败原因根本不是同一回事。
    """
    before_mode = str(baseline.get("mode", "未知"))
    after_mode = str(current.get("mode", "未知"))
    if before_mode != after_mode:
        raise ReportFormatError(
            f"两份报告的评测模式不同（{before_mode} / {after_mode}），无法对照。"
        )

    before = _records(baseline)
    after = _records(current)
    shared = sorted(before.keys() & after.keys())

    fixed: list[CaseDelta] = []
    regressed: list[CaseDelta] = []
    changed: list[CaseDelta] = []
    for case_id in shared:
        old, new = before[case_id], after[case_id]
        if old.passed and not new.passed:
            regressed.append(CaseDelta(case_id, old.label, new.label))
        elif not old.passed and new.passed:
            fixed.append(CaseDelta(case_id, old.label, new.label))
        elif not old.passed and old.primary_failure != new.primary_failure:
            # 两次都失败，但原因换了：可能修对了一半，也可能只是换个地方坏。
            changed.append(CaseDelta(case_id, old.label, new.label))

    added = [
        CaseDelta(case_id, "不存在", after[case_id].label)
        for case_id in sorted(after.keys() - before.keys())
    ]
    removed = [
        CaseDelta(case_id, before[case_id].label, "不存在")
        for case_id in sorted(before.keys() - after.keys())
    ]

    before_summary, after_summary = _summary(baseline), _summary(current)
    metrics = tuple(
        MetricDelta(name, before_summary.get(name), after_summary.get(name))
        for name in sorted(before_summary.keys() | after_summary.keys())
    )

    return Comparison(
        mode=after_mode,
        prompt_before=_meta(baseline, "prompt_hash"),
        prompt_after=_meta(current, "prompt_hash"),
        model_before=_meta(baseline, "model"),
        model_after=_meta(current, "model"),
        passed_before=sum(1 for record in before.values() if record.passed),
        passed_after=sum(1 for record in after.values() if record.passed),
        total_before=len(before),
        total_after=len(after),
        fixed=tuple(fixed),
        regressed=tuple(regressed),
        changed_failure=tuple(changed),
        added=tuple(added),
        removed=tuple(removed),
        metrics=metrics,
    )


def _format(name: str, value: float | None) -> str:
    if value is None:
        return "无数据"
    if name.endswith(_PERCENT_SUFFIX):
        return f"{value:.1%}"
    return f"{value:.2f}"


def _case_block(title: str, deltas: Sequence[CaseDelta]) -> list[str]:
    if not deltas:
        return []
    lines = ["", f"{title}（{len(deltas)}）"]
    lines.extend(
        f"  {delta.case_id:<38}{delta.before} -> {delta.after}" for delta in deltas
    )
    return lines


def _metric_lines(metrics: Sequence[MetricDelta]) -> list[str]:
    movers = [metric for metric in metrics if metric.delta not in (None, 0.0)]
    if not movers:
        return []
    lines = ["", "指标变化"]
    for metric in movers:
        assert metric.delta is not None
        arrow = "+" if metric.delta > 0 else ""
        lines.append(
            f"  {metric.name:<{WIDTH}}"
            f"{_format(metric.name, metric.before)} -> "
            f"{_format(metric.name, metric.after)}"
            f"  ({arrow}{_format(metric.name, metric.delta)})"
        )
    return lines


def render(comparison: Comparison) -> str:
    head = [
        "评测对照",
        f"模式：{comparison.mode}",
        f"prompt：{comparison.prompt_before} -> {comparison.prompt_after}"
        + ("（已改动）" if comparison.prompt_changed else "（未改动）"),
    ]
    if comparison.model_before != comparison.model_after:
        head.append(f"模型：{comparison.model_before} -> {comparison.model_after}")
    head.extend(
        [
            "",
            f"通过：{comparison.passed_before}/{comparison.total_before}"
            f" -> {comparison.passed_after}/{comparison.total_after}",
        ]
    )

    body = [
        *_case_block("回归（通过变失败）", comparison.regressed),
        *_case_block("修复（失败变通过）", comparison.fixed),
        *_case_block("失败原因改变", comparison.changed_failure),
        *_case_block("新增用例", comparison.added),
        *_case_block("移除用例", comparison.removed),
        *_metric_lines(comparison.metrics),
    ]
    if not body:
        body = ["", "逐用例结果完全一致。"]

    return "\n".join([*head, *body, "", f"判定：{comparison.verdict}"])
