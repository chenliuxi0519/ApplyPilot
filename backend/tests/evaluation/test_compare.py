"""两次评测的对照必须分清"修好了"和"换个地方坏"。"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.evaluation.compare import (
    ReportFormatError,
    compare,
    load_report,
    render,
)


def _report(
    *,
    cases: list[tuple[str, bool, str | None]],
    mode: str = "deterministic",
    prompt_hash: str = "aaaaaaaaaaaa",
    model: str = "scripted",
    summary: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "metadata": {"prompt_hash": prompt_hash, "model": model},
        "summary": summary or {},
        "cases": [
            {"id": case_id, "passed": passed, "primary_failure": failure}
            for case_id, passed, failure in cases
        ],
    }


def test_a_fix_and_a_regression_are_counted_separately() -> None:
    """总分持平也可能是"修好一个又弄坏一个"，这正是要拆开看的原因。"""
    baseline = _report(cases=[("a", True, None), ("b", False, "wrong_tool")])
    current = _report(cases=[("a", False, "policy_error"), ("b", True, None)])

    result = compare(baseline=baseline, current=current)

    assert [delta.case_id for delta in result.regressed] == ["a"]
    assert [delta.case_id for delta in result.fixed] == ["b"]
    assert result.passed_before == result.passed_after == 1
    assert result.has_regression is True
    assert result.verdict.startswith("回归")


def test_a_clean_improvement_is_called_an_improvement() -> None:
    baseline = _report(cases=[("a", False, "wrong_tool"), ("b", True, None)])
    current = _report(cases=[("a", True, None), ("b", True, None)])

    result = compare(baseline=baseline, current=current)

    assert result.has_regression is False
    assert [delta.case_id for delta in result.fixed] == ["a"]
    assert result.verdict.startswith("改进")


def test_a_new_case_is_not_counted_as_a_fix() -> None:
    """数据集加了题，不等于模型变好了。"""
    baseline = _report(cases=[("a", True, None)])
    current = _report(cases=[("a", True, None), ("b", True, None)])

    result = compare(baseline=baseline, current=current)

    assert result.fixed == ()
    assert [delta.case_id for delta in result.added] == ["b"]
    assert result.has_regression is False


def test_a_removed_case_is_not_counted_as_a_regression() -> None:
    baseline = _report(cases=[("a", True, None), ("b", False, "wrong_tool")])
    current = _report(cases=[("a", True, None)])

    result = compare(baseline=baseline, current=current)

    assert result.regressed == ()
    assert [delta.case_id for delta in result.removed] == ["b"]


def test_a_still_failing_case_reports_a_changed_reason() -> None:
    """两次都挂，但原因换了——可能修对了一半，值得单独提醒。"""
    baseline = _report(cases=[("a", False, "wrong_tool")])
    current = _report(cases=[("a", False, "policy_error")])

    result = compare(baseline=baseline, current=current)

    assert result.fixed == ()
    assert result.regressed == ()
    assert [delta.case_id for delta in result.changed_failure] == ["a"]
    assert result.verdict.startswith("存疑")


def test_an_unchanged_run_is_flat() -> None:
    baseline = _report(cases=[("a", True, None)])
    current = _report(cases=[("a", True, None)])

    result = compare(baseline=baseline, current=current)

    assert result.verdict.startswith("持平")
    assert "逐用例结果完全一致" in render(result)


def test_comparing_different_modes_is_refused() -> None:
    """脚本驱动和模型驱动的失败原因不是一回事，混着比没有意义。"""
    baseline = _report(cases=[("a", True, None)], mode="deterministic")
    current = _report(cases=[("a", True, None)], mode="real")

    with pytest.raises(ReportFormatError, match="评测模式不同"):
        compare(baseline=baseline, current=current)


def test_a_changed_prompt_is_surfaced() -> None:
    baseline = _report(cases=[("a", True, None)], prompt_hash="aaaaaaaaaaaa")
    current = _report(cases=[("a", True, None)], prompt_hash="bbbbbbbbbbbb")

    result = compare(baseline=baseline, current=current)

    assert result.prompt_changed is True
    assert "aaaaaaaaaaaa -> bbbbbbbbbbbb" in render(result)
    assert "（已改动）" in render(result)


def test_only_moving_metrics_are_printed() -> None:
    baseline = _report(
        cases=[("a", True, None)],
        summary={"clean_pass_rate": 0.5, "mean_steps": 2.0},
    )
    current = _report(
        cases=[("a", True, None)],
        summary={"clean_pass_rate": 0.75, "mean_steps": 2.0},
    )

    text = render(compare(baseline=baseline, current=current))

    assert "clean_pass_rate" in text
    assert "50.0% -> 75.0%" in text
    assert "mean_steps" not in text


def test_a_missing_metric_does_not_crash_the_diff() -> None:
    baseline = _report(cases=[("a", True, None)], summary={"mean_steps": None})
    current = _report(cases=[("a", True, None)], summary={"p95_steps": 3.0})

    text = render(compare(baseline=baseline, current=current))

    assert "判定：" in text


def test_a_report_without_cases_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text(json.dumps({"mode": "deterministic"}), encoding="utf-8")

    with pytest.raises(ReportFormatError, match="缺少 cases"):
        load_report(path)


def test_a_non_json_report_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("not json at all", encoding="utf-8")

    with pytest.raises(ReportFormatError, match="不是合法 JSON"):
        load_report(path)


def test_a_missing_report_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ReportFormatError, match="无法读取"):
        load_report(tmp_path / "nope.json")


def test_a_round_trip_through_disk_keeps_the_comparison(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps(_report(cases=[("a", False, "wrong_tool")]), ensure_ascii=False),
        encoding="utf-8",
    )

    result = compare(
        baseline=load_report(path),
        current=_report(cases=[("a", True, None)]),
    )

    assert [delta.case_id for delta in result.fixed] == ["a"]
