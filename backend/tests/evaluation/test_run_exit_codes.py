"""带基线运行时，回归必须让退出码非零——CI 靠这个卡住。"""

import json
from pathlib import Path

import pytest

from app.agent.state import AgentStatus
from app.evaluation import run as run_module
from app.evaluation.case import Category
from app.evaluation.scoring import CaseOutcome, Failure, FailureKind
from app.modules.agent_runs.metrics import RunMetrics

CASE_ID = "profile_read_001"


def _outcome(*, passed: bool) -> CaseOutcome:
    failures = (
        () if passed else (Failure(kind=FailureKind.WRONG_TOOL, detail="调错了工具"),)
    )
    return CaseOutcome(
        case_id=CASE_ID,
        category=Category.PROFILE,
        failures=failures,
        attempted_tools=("get_user_profile",),
        succeeded_tools=("get_user_profile",),
        confirmed=False,
        expects_confirmation=False,
        final_status=AgentStatus.COMPLETED,
        expected_tools=frozenset({"get_user_profile"}),
        forbidden_tools=frozenset(),
        expected_order=(),
        order_ok=None,
        metrics=RunMetrics(
            task_success=passed,
            total_steps=2,
            total_tool_calls=1,
            tool_error_count=0,
            confirmation_count=0,
            approval_count=0,
            rejection_count=0,
            total_tool_latency_ms=10,
            run_duration_ms=30,
        ),
        tool_call_events=1,
        tool_error_events=0,
        unexpected_error_events=0,
        effects=(),
    )


@pytest.fixture
def baseline(tmp_path: Path) -> Path:
    """一份"这个用例上次是通过的"的基线。"""
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps(
            {
                "mode": "deterministic",
                "metadata": {"prompt_hash": "aaaaaaaaaaaa", "model": "scripted"},
                "summary": {},
                "cases": [{"id": CASE_ID, "passed": True, "primary_failure": None}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _stub_run_cases(monkeypatch: pytest.MonkeyPatch, *, passed: bool) -> None:
    monkeypatch.setattr(
        run_module, "run_cases", lambda *args, **kwargs: [_outcome(passed=passed)]
    )


def test_a_regression_against_the_baseline_fails_the_run(
    monkeypatch: pytest.MonkeyPatch, baseline: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_run_cases(monkeypatch, passed=False)

    code = run_module.main(["--baseline", str(baseline), "--case-id", CASE_ID])

    assert code == run_module.EXIT_FAILED
    assert "回归（通过变失败）" in capsys.readouterr().out


def test_no_regression_against_the_baseline_passes(
    monkeypatch: pytest.MonkeyPatch, baseline: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_run_cases(monkeypatch, passed=True)

    code = run_module.main(["--baseline", str(baseline), "--case-id", CASE_ID])

    assert code == run_module.EXIT_OK
    assert "判定：持平" in capsys.readouterr().out


def test_an_unreadable_baseline_stops_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """基线读不了就别假装比过了，也别当成通过。"""
    _stub_run_cases(monkeypatch, passed=True)

    code = run_module.main(
        ["--baseline", str(tmp_path / "missing.json"), "--case-id", CASE_ID]
    )

    assert code == run_module.EXIT_UNAVAILABLE


def test_without_a_baseline_the_exit_code_only_reflects_this_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_run_cases(monkeypatch, passed=True)

    assert run_module.main(["--case-id", CASE_ID]) == run_module.EXIT_OK
