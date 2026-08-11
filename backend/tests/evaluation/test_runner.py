import dataclasses
import uuid

import pytest
from sqlmodel import Session, col, func, select

from app.agent.state import AgentStatus
from app.core.db import engine
from app.evaluation import run as run_cli
from app.evaluation.case import NO_CHANGE, Category, EffectCheck, EffectKind
from app.evaluation.dataset import cases
from app.evaluation.runner import EVAL_EMAIL_PREFIX, Mode, run_case, run_cases
from app.evaluation.scoring import FailureKind
from app.models import User


def _case(case_id: str):
    (case,) = cases(case_ids=[case_id])
    return case


def _eval_user_count(session: Session) -> int:
    return session.exec(
        select(func.count())
        .select_from(User)
        .where(col(User.email).like(f"{EVAL_EMAIL_PREFIX}%"))
    ).one()


def test_a_read_only_case_passes_and_records_a_run() -> None:
    result = run_case(_case("profile_read_001"), engine=engine)
    assert result.outcome.passed, result.outcome.failures
    assert result.outcome.attempted_tools == ("get_user_profile",)
    assert result.run_id is not None


def test_a_write_case_leaves_the_expected_row_behind() -> None:
    outcome = run_case(_case("application_create_001"), engine=engine).outcome
    assert outcome.passed, outcome.failures
    assert outcome.succeeded_tools == ("create_application",)


def test_a_high_risk_case_pauses_without_touching_the_database() -> None:
    outcome = run_case(_case("hitl_submit_001"), engine=engine).outcome
    assert outcome.passed, outcome.failures
    assert outcome.confirmed
    assert outcome.final_status is AgentStatus.WAITING_CONFIRMATION
    assert all(result.passed for result in outcome.effects)


def test_approving_applies_the_change_and_rejecting_does_not() -> None:
    approved = run_case(_case("hitl_approve_005"), engine=engine).outcome
    rejected = run_case(_case("hitl_reject_006"), engine=engine).outcome
    assert approved.passed, approved.failures
    assert rejected.passed, rejected.failures

    assert len(approved.effects) == 2
    assert len(rejected.effects) == 2


def test_the_evaluation_user_is_cleaned_up(db: Session) -> None:
    before = _eval_user_count(db)
    run_case(_case("profile_read_001"), engine=engine)
    db.expire_all()
    assert _eval_user_count(db) == before


def test_keep_leaves_the_user_behind(db: Session) -> None:
    before = _eval_user_count(db)
    run_case(_case("profile_read_001"), engine=engine, keep=True)
    db.expire_all()
    assert _eval_user_count(db) == before + 1


def test_the_runner_can_actually_fail() -> None:
    broken = dataclasses.replace(
        _case("profile_read_001"),
        id="mutated_001",
        expected_tools=frozenset({"create_application"}),
    )
    outcome = run_case(broken, engine=engine).outcome
    assert not outcome.passed
    assert outcome.has(FailureKind.MISSING_TOOL)


def test_a_wrong_business_expectation_is_caught() -> None:
    broken = dataclasses.replace(
        _case("application_create_001"),
        id="mutated_002",
        expected_effect=EffectCheck(
            kind=EffectKind.APPLICATION_COUNT, params={"count": 7}
        ),
    )
    outcome = run_case(broken, engine=engine).outcome
    assert not outcome.passed
    assert outcome.has(FailureKind.BUSINESS_EFFECT_MISMATCH)


def test_a_missed_confirmation_expectation_is_caught() -> None:
    broken = dataclasses.replace(
        _case("hitl_submit_001"),
        id="mutated_003",
        expect_confirmation=False,
        expected_final_status=AgentStatus.COMPLETED,
        expected_effect=NO_CHANGE,
    )
    outcome = run_case(broken, engine=engine).outcome
    assert not outcome.passed
    assert outcome.has(FailureKind.CONFIRMATION_ERROR)


def test_an_unrunnable_case_is_reported_rather_than_crashing_the_suite() -> None:
    broken = dataclasses.replace(_case("profile_read_001"), id="m4", setup="nope")
    outcome = run_case(broken, engine=engine).outcome
    assert not outcome.passed
    assert outcome.crash is not None
    assert outcome.primary is None


def test_one_failing_case_does_not_stop_the_rest() -> None:
    broken = dataclasses.replace(_case("profile_read_001"), id="m5", setup="nope")
    outcomes = run_cases([broken, _case("profile_read_001")], engine=engine)
    assert len(outcomes) == 2
    assert outcomes[1].passed


def test_fail_fast_stops_after_the_first_failure() -> None:
    broken = dataclasses.replace(_case("profile_read_001"), id="m6", setup="nope")
    outcomes = run_cases(
        [broken, _case("profile_read_001")], engine=engine, fail_fast=True
    )
    assert len(outcomes) == 1


def test_repeat_runs_a_case_more_than_once() -> None:
    outcomes = run_cases([_case("profile_read_001")], engine=engine, repeat=2)
    assert len(outcomes) == 2


def test_a_conditional_script_only_retries_after_the_error_arrives() -> None:
    outcome = run_case(_case("recovery_invalid_arguments_002"), engine=engine).outcome
    assert outcome.passed, outcome.failures
    assert outcome.attempted_tools == ("create_application", "create_application")
    assert outcome.succeeded_tools == ("create_application",)


def test_a_batch_with_one_high_risk_call_runs_none_of_it() -> None:
    outcome = run_case(_case("hitl_batch_pause_008"), engine=engine).outcome
    assert outcome.passed, outcome.failures
    assert "get_user_profile" not in outcome.attempted_tools


def test_every_real_case_message_resolves_against_its_fixture(db: Session) -> None:
    from app.evaluation.fixtures import build_fixture
    from app.evaluation.runner import create_eval_user, delete_eval_user

    for case in cases(real_only=True):
        user = create_eval_user(db)
        try:
            data = build_fixture(case.setup, session=db, user_id=user.id)
            rendered = case.render_message(data.values)
            assert "{" not in rendered, f"{case.id} left a placeholder unfilled"
        finally:
            delete_eval_user(db, user.id)


def test_cli_runs_a_single_case(capsys: pytest.CaptureFixture[str]) -> None:
    code = run_cli.main(["--case-id", "profile_read_001"])
    assert code == run_cli.EXIT_OK
    output = capsys.readouterr().out
    assert "DETERMINISTIC RUNTIME EVALUATION" in output
    assert "Cases: 1" in output
    assert "Tool Selection Accuracy" not in output


def test_cli_runs_a_category(capsys: pytest.CaptureFixture[str]) -> None:
    code = run_cli.main(["--category", Category.HITL.value])
    assert code == run_cli.EXIT_OK
    assert f"Cases: {len(cases(category=Category.HITL))}" in capsys.readouterr().out


def test_cli_reports_an_empty_selection(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_cli.main(["--case-id", str(uuid.uuid4())]) == run_cli.EXIT_UNAVAILABLE
    assert "No cases matched" in capsys.readouterr().out


def test_cli_can_list_without_touching_the_database(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_cli.main(["--list"]) == run_cli.EXIT_OK
    assert "cases" in capsys.readouterr().out


def test_cli_writes_json(tmp_path) -> None:
    import json

    path = tmp_path / "result.json"
    run_cli.main(["--case-id", "profile_read_001", "--json", str(path)])
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["mode"] == Mode.DETERMINISTIC.value
    assert payload["cases"][0]["id"] == "profile_read_001"
