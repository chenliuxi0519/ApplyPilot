import pytest

from app.agent.anthropic_client import AgentNotConfiguredError
from app.core.config import settings
from app.evaluation import run as run_cli
from app.evaluation.dataset import cases
from app.evaluation.runner import Mode, build_model

AGENT_SETTINGS = ("AGENT_BASE_URL", "AGENT_API_KEY", "AGENT_MODEL")


def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AGENT_BASE_URL", "https://example.invalid/anthropic")
    monkeypatch.setattr(settings, "AGENT_API_KEY", "not-a-real-key")
    monkeypatch.setattr(settings, "AGENT_MODEL", "deepseek-v4-flash")


def test_the_real_subset_is_a_subset_of_the_dataset() -> None:
    real = cases(real_only=True)
    assert real
    assert {case.id for case in real} <= {case.id for case in cases()}


@pytest.mark.parametrize("absent", AGENT_SETTINGS)
def test_any_missing_setting_refuses_to_build_a_real_model(
    monkeypatch: pytest.MonkeyPatch, absent: str
) -> None:
    _configured(monkeypatch)
    monkeypatch.setattr(settings, absent, None)
    (case,) = cases(case_ids=["profile_read_001"])

    with pytest.raises(AgentNotConfiguredError):
        build_model(case, None, Mode.REAL)  # type: ignore[arg-type]


def test_a_missing_base_url_does_not_fall_back_to_the_official_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.anthropic_client import AnthropicModelClient

    _configured(monkeypatch)
    monkeypatch.setattr(settings, "AGENT_BASE_URL", None)
    with pytest.raises(AgentNotConfiguredError, match="AGENT_BASE_URL"):
        AnthropicModelClient()


def test_missing_settings_are_reported_by_name() -> None:
    assert set(settings.missing_agent_settings()) <= set(AGENT_SETTINGS)


def test_the_cli_skips_real_mode_when_it_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(settings, "AGENT_API_KEY", None)
    calls: list[object] = []
    monkeypatch.setattr(
        run_cli, "run_cases", lambda *args, **kwargs: calls.append(args) or []
    )

    code = run_cli.main(["--mode", "real"])

    assert code == run_cli.EXIT_UNAVAILABLE
    assert "AGENT_API_KEY not set" in capsys.readouterr().out

    assert calls == []


@pytest.mark.skipif(
    not settings.agent_is_configured, reason="the agent endpoint is not configured"
)
def test_a_real_case_runs_when_the_endpoint_is_configured() -> None:
    from app.core.db import engine
    from app.evaluation.runner import run_case

    (case,) = cases(case_ids=["search_singapore_ai_001"])
    outcome = run_case(case, engine=engine, mode=Mode.REAL).outcome
    assert "search_programs" in outcome.attempted_tools
