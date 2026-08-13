from app.agent.state import AgentStatus
from app.evaluation.case import Category, EffectKind
from app.evaluation.dataset import DATASET, cases
from app.evaluation.fixtures import fixture_names
from app.evaluation.scripts import script_names
from app.tools.registry import BUSINESS_TOOLS

TOOL_NAMES = frozenset(definition.name for definition in BUSINESS_TOOLS)


def test_case_ids_are_unique() -> None:
    ids = [case.id for case in DATASET]
    assert len(ids) == len(set(ids))


def test_the_dataset_is_small_and_deliberate() -> None:
    # 上限从 50 放宽到 100：新增了 evidence 与 security 两组场景。
    # 仍然设上限——用例要人工挑选，不是越多越好。
    assert 30 <= len(DATASET) <= 100


def test_every_expected_tool_exists() -> None:
    for case in DATASET:
        unknown = case.expected_tools - TOOL_NAMES
        assert not unknown, f"{case.id} expects unknown tools {sorted(unknown)}"


def test_every_forbidden_tool_exists() -> None:
    for case in DATASET:
        unknown = case.forbidden_tools - TOOL_NAMES
        assert not unknown, f"{case.id} forbids unknown tools {sorted(unknown)}"


def test_expected_and_forbidden_never_overlap() -> None:
    for case in DATASET:
        assert not case.expected_tools & case.forbidden_tools, case.id


def test_every_fixture_resolves() -> None:
    known = fixture_names()
    for case in DATASET:
        assert case.setup in known, f"{case.id} names unknown fixture {case.setup}"


def test_every_script_resolves() -> None:
    known = script_names()
    for case in DATASET:
        assert case.script is not None, f"{case.id} has no deterministic script"
        assert case.script in known, f"{case.id} names unknown script {case.script}"


def test_ordered_tools_are_also_expected() -> None:
    for case in DATASET:
        assert set(case.expected_tool_order) <= case.expected_tools, case.id


def test_resume_only_where_a_pause_is_expected() -> None:
    for case in DATASET:
        if case.resume is not None:
            assert case.expect_confirmation, case.id


def test_a_case_that_is_not_resumed_ends_waiting() -> None:
    for case in DATASET:
        if case.expect_confirmation and case.resume is None:
            assert case.expected_final_status is AgentStatus.WAITING_CONFIRMATION, (
                case.id
            )


def test_pause_effects_only_on_pausing_cases() -> None:
    for case in DATASET:
        if case.effect_at_pause is not None:
            assert case.expect_confirmation, case.id


def test_every_category_is_covered() -> None:
    covered = {case.category for case in DATASET}
    assert covered == set(Category)


def test_hitl_has_a_negative_case() -> None:
    hitl = [case for case in DATASET if case.category is Category.HITL]
    assert any(not case.expect_confirmation for case in hitl)


def test_high_risk_cases_check_that_nothing_moved_first() -> None:
    for case in DATASET:
        if case.resume is not None:
            assert case.effect_at_pause is not None, case.id
            assert case.effect_at_pause.kind is EffectKind.NO_CHANGE, case.id


def test_the_real_subset_is_between_ten_and_fifteen() -> None:
    real = [case for case in DATASET if case.real]
    assert 10 <= len(real) <= 15


def test_real_messages_carry_the_ids_their_fixture_creates() -> None:
    needs_id = {
        "shortlisted_application",
        "preparing_application",
        "prepared_application",
        "ready_application",
        "submitted_application",
        "program",
    }
    for case in DATASET:
        if case.real and case.setup in needs_id:
            assert "{" in case.user_message, case.id


def test_selection_by_category_and_id() -> None:
    hitl = cases(category=Category.HITL)
    assert hitl and all(case.category is Category.HITL for case in hitl)
    assert [case.id for case in cases(case_ids=["hitl_submit_001"])] == [
        "hitl_submit_001"
    ]
    assert all(case.real for case in cases(real_only=True))


def test_a_case_exports_as_json_safe_data() -> None:
    import json

    payload = [case.to_dict() for case in DATASET]
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload
