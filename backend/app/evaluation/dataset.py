import uuid
from collections.abc import Sequence

from app.agent.budget import Budget
from app.agent.model import ModelResponse, ModelToolCall
from app.agent.state import AgentStatus
from app.evaluation.case import (
    NO_CHANGE,
    Category,
    EffectCheck,
    EffectKind,
    EvaluationCase,
    FixtureData,
    ResumeDecision,
)
from app.evaluation.scripts import Step, answer, call, calls, error_code_of, script
from app.harness import ToolErrorCode, ToolResult

DONE = "好的，我已经处理完了。"


MISSING_PROGRAM_ID = "00000000-0000-4000-8000-000000000000"


@script("read_profile")
def _read_profile(data: FixtureData) -> Sequence[Step]:
    del data
    return [calls(call("get_user_profile", {})), answer(DONE)]


@script("set_career_goal")
def _set_career_goal(data: FixtureData) -> Sequence[Step]:
    del data
    return [
        calls(call("update_user_profile", {"career_goal": "AI 平台工程师"})),
        answer(DONE),
    ]


@script("set_target_regions")
def _set_target_regions(data: FixtureData) -> Sequence[Step]:
    del data
    return [
        calls(call("update_user_profile", {"target_regions": ["united_kingdom"]})),
        answer(DONE),
    ]


@script("set_ielts")
def _set_ielts(data: FixtureData) -> Sequence[Step]:
    del data
    return [calls(call("update_user_profile", {"ielts_overall": 7.5})), answer(DONE)]


@script("set_gpa")
def _set_gpa(data: FixtureData) -> Sequence[Step]:
    del data
    return [
        calls(call("update_user_profile", {"gpa_value": 3.8, "gpa_scale": 4.0})),
        answer(DONE),
    ]


@script("empty_profile_update")
def _empty_profile_update(data: FixtureData) -> Sequence[Step]:
    del data
    return [calls(call("update_user_profile", {})), answer(DONE)]


PROFILE_CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        id="profile_read_001",
        category=Category.PROFILE,
        user_message="帮我看一下我现在的背景资料。",
        setup="profile",
        script="read_profile",
        expected_tools=frozenset({"get_user_profile"}),
        real=True,
    ),
    EvaluationCase(
        id="profile_read_missing_002",
        category=Category.PROFILE,
        user_message="帮我看一下我现在的背景资料。",
        setup="empty",
        script="read_profile",
        expected_tools=frozenset({"get_user_profile"}),
        expected_error_codes=frozenset({ToolErrorCode.NOT_FOUND}),
        forbidden_tools=frozenset({"update_user_profile"}),
        notes="档案不存在时应明确告知，不能替用户编造。",
    ),
    EvaluationCase(
        id="profile_career_goal_003",
        category=Category.PROFILE,
        user_message="把我的职业目标改成 AI 平台工程师。",
        setup="profile",
        script="set_career_goal",
        expected_tools=frozenset({"update_user_profile"}),
        expected_effect=EffectCheck(
            kind=EffectKind.PROFILE_FIELD,
            params={"field": "career_goal", "value": "AI 平台工程师"},
        ),
    ),
    EvaluationCase(
        id="profile_target_regions_004",
        category=Category.PROFILE,
        user_message="我改主意了，只想申请英国。",
        setup="profile",
        script="set_target_regions",
        expected_tools=frozenset({"update_user_profile"}),
        expected_effect=EffectCheck(
            kind=EffectKind.PROFILE_FIELD,
            params={"field": "target_regions", "value": "united_kingdom"},
        ),
    ),
    EvaluationCase(
        id="profile_ielts_005",
        category=Category.PROFILE,
        user_message="我雅思重考了，总分 7.5，帮我更新。",
        setup="profile",
        script="set_ielts",
        expected_tools=frozenset({"update_user_profile"}),
        expect_confirmation=True,
        resume=ResumeDecision.APPROVE,
        effect_at_pause=NO_CHANGE,
        expected_effect=EffectCheck(
            kind=EffectKind.PROFILE_FIELD,
            params={"field": "ielts_overall", "value": "7.5"},
        ),
        real=True,
        notes="工具默认低风险，但修改成绩字段必须升级为高风险。",
    ),
    EvaluationCase(
        id="profile_gpa_006",
        category=Category.PROFILE,
        user_message="我的 GPA 是 3.8/4.0，帮我记一下。",
        setup="profile",
        script="set_gpa",
        expected_tools=frozenset({"update_user_profile"}),
        expect_confirmation=True,
        resume=ResumeDecision.REJECT,
        effect_at_pause=NO_CHANGE,
        expected_effect=NO_CHANGE,
        notes="用户拒绝后，数据库中的 GPA 必须保持不变。",
    ),
    EvaluationCase(
        id="profile_empty_update_007",
        category=Category.PROFILE,
        user_message="更新一下我的资料。",
        setup="profile",
        script="empty_profile_update",
        expected_tools=frozenset({"update_user_profile"}),
        expected_error_codes=frozenset({ToolErrorCode.INVALID_INPUT}),
        notes="空更新应在进入权限判断和数据库会话前被参数校验拒绝。",
    ),
)


def _search(**filters: object) -> Step:
    return calls(call("search_programs", dict(filters)))


@script("search_singapore_ai")
def _search_singapore_ai(data: FixtureData) -> Sequence[Step]:
    del data
    return [_search(region="singapore", field_tags=["ai"]), answer(DONE)]


@script("search_hongkong_cs")
def _search_hongkong_cs(data: FixtureData) -> Sequence[Step]:
    del data
    return [_search(region="hong_kong", field_tags=["cs"]), answer(DONE)]


@script("search_uk_ml")
def _search_uk_ml(data: FixtureData) -> Sequence[Step]:
    del data
    return [_search(region="united_kingdom", field_tags=["ml"]), answer(DONE)]


def _first_program_id(results: Sequence[ToolResult]) -> str | None:
    for result in results:
        if result.tool_name == "search_programs" and result.output is not None:
            payload = result.output.model_dump(mode="json")
            programs = payload.get("data") or []
            if programs:
                return str(programs[0]["program_id"])
    return None


@script("search_then_requirements")
def _search_then_requirements(data: FixtureData) -> Sequence[Step]:
    del data

    def then(results: Sequence[ToolResult]) -> ModelResponse:
        program_id = _first_program_id(results)
        if program_id is None:
            return answer("没有找到对应的项目。")
        return calls(
            call(
                "get_program_requirements",
                {"program_id": program_id},
                call_id="toolu_req",
            )
        )

    return [
        _search(university="HKUST", field_tags=["ai"]),
        then,
        answer(DONE),
    ]


@script("requirements_of_fixture_program")
def _requirements_of_fixture_program(data: FixtureData) -> Sequence[Step]:
    return [
        calls(
            call(
                "get_program_requirements",
                {"program_id": str(data.id_of("program_id"))},
            )
        ),
        answer(DONE),
    ]


@script("requirements_of_unknown_program")
def _requirements_of_unknown_program(data: FixtureData) -> Sequence[Step]:
    del data
    return [
        calls(call("get_program_requirements", {"program_id": str(uuid.uuid4())})),
        answer(DONE),
    ]


PROGRAM_SEARCH_CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        id="search_singapore_ai_001",
        category=Category.PROGRAM_SEARCH,
        user_message="帮我找一下新加坡的人工智能硕士项目。",
        setup="catalog",
        script="search_singapore_ai",
        expected_tools=frozenset({"search_programs"}),
        real=True,
    ),
    EvaluationCase(
        id="search_hongkong_cs_002",
        category=Category.PROGRAM_SEARCH,
        user_message="香港有哪些计算机科学的硕士？",
        setup="catalog",
        script="search_hongkong_cs",
        expected_tools=frozenset({"search_programs"}),
    ),
    EvaluationCase(
        id="search_region_and_field_003",
        category=Category.PROGRAM_SEARCH,
        user_message="英国的机器学习方向有什么项目？",
        setup="catalog",
        script="search_uk_ml",
        expected_tools=frozenset({"search_programs"}),
    ),
    EvaluationCase(
        id="search_then_requirements_004",
        category=Category.PROGRAM_SEARCH,
        user_message="HKUST 的人工智能硕士有什么申请要求？",
        setup="catalog",
        script="search_then_requirements",
        expected_tools=frozenset({"search_programs", "get_program_requirements"}),
        expected_tool_order=("search_programs", "get_program_requirements"),
        real=True,
        notes="读取项目要求前必须先查到项目 ID。",
    ),
    EvaluationCase(
        id="search_unknown_program_005",
        category=Category.PROGRAM_SEARCH,
        user_message="帮我查一下这个项目的要求。",
        setup="catalog",
        script="requirements_of_unknown_program",
        expected_tools=frozenset({"get_program_requirements"}),
        expected_error_codes=frozenset({ToolErrorCode.NOT_FOUND}),
    ),
    EvaluationCase(
        id="search_conflicted_requirement_006",
        category=Category.PROGRAM_SEARCH,
        user_message="这个项目的雅思要求是多少？",
        setup="conflicted_requirement",
        script="requirements_of_fixture_program",
        expected_tools=frozenset({"get_program_requirements"}),
        notes="争议中的要求必须携带冲突状态，不能作为确定信息返回。",
    ),
)


@script("profile_then_requirements")
def _profile_then_requirements(data: FixtureData) -> Sequence[Step]:
    del data

    def then(results: Sequence[ToolResult]) -> ModelResponse:
        program_id = _first_program_id(results)
        if program_id is None:
            return answer("没有找到对应的项目。")
        return calls(
            call(
                "get_program_requirements",
                {"program_id": program_id},
                call_id="toolu_req",
            )
        )

    return [
        calls(
            call("get_user_profile", {}, call_id="toolu_profile"),
            call(
                "search_programs",
                {"university": "NTU", "field_tags": ["ai"]},
                call_id="toolu_search",
            ),
        ),
        then,
        answer(DONE),
    ]


@script("profile_missing_then_ask")
def _profile_missing_then_ask(data: FixtureData) -> Sequence[Step]:
    del data

    def then(results: Sequence[ToolResult]) -> ModelResponse:
        if error_code_of(results) == ToolErrorCode.NOT_FOUND.value:
            return answer("我还不知道你的本科背景和语言成绩，能先告诉我吗？")
        return answer(DONE)

    return [calls(call("get_user_profile", {})), then]


@script("compare_two_programs")
def _compare_two_programs(data: FixtureData) -> Sequence[Step]:
    del data

    def then(results: Sequence[ToolResult]) -> ModelResponse:
        program_id = _first_program_id(results)
        if program_id is None:
            return answer("没有找到对应的项目。")
        return calls(
            call(
                "get_program_requirements",
                {"program_id": program_id},
                call_id="toolu_req",
            )
        )

    return [
        _search(field_tags=["ai"], region="hong_kong"),
        then,
        answer(DONE),
    ]


PROGRAM_ANALYSIS_CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        id="analysis_profile_then_requirements_001",
        category=Category.PROGRAM_ANALYSIS,
        user_message="以我的背景，NTU 的 AI 硕士我够得上吗？",
        setup="profile_and_catalog",
        script="profile_then_requirements",
        expected_tools=frozenset(
            {"get_user_profile", "search_programs", "get_program_requirements"}
        ),
        expected_tool_order=("get_user_profile", "get_program_requirements"),
        real=True,
        notes="匹配判断必须同时读取用户数据和项目要求。",
    ),
    EvaluationCase(
        id="analysis_missing_profile_002",
        category=Category.PROGRAM_ANALYSIS,
        user_message="以我的背景，我能申请到什么样的项目？",
        setup="catalog",
        script="profile_missing_then_ask",
        expected_tools=frozenset({"get_user_profile"}),
        forbidden_tools=frozenset({"update_user_profile"}),
        expected_error_codes=frozenset({ToolErrorCode.NOT_FOUND}),
        notes="没有档案时应向用户追问，不能虚构背景。",
    ),
    EvaluationCase(
        id="analysis_requirements_absent_003",
        category=Category.PROGRAM_ANALYSIS,
        user_message="这个项目要求雅思多少分？",
        setup="program",
        script="requirements_of_fixture_program",
        expected_tools=frozenset({"get_program_requirements"}),
        notes="项目没有已发布要求时返回空列表，任何环节都不能擅自补数值。",
    ),
    EvaluationCase(
        id="analysis_compare_two_004",
        category=Category.PROGRAM_ANALYSIS,
        user_message="香港的几个 AI 硕士，哪个要求更高？",
        setup="profile_and_catalog",
        script="compare_two_programs",
        expected_tools=frozenset({"search_programs", "get_program_requirements"}),
        expected_tool_order=("search_programs", "get_program_requirements"),
    ),
)


@script("create_application")
def _create_application(data: FixtureData) -> Sequence[Step]:
    return [
        calls(
            call(
                "create_application",
                {
                    "program_id": str(data.id_of("program_id")),
                    "application_cycle": "2026/27",
                },
            )
        ),
        answer(DONE),
    ]


@script("create_duplicate_application")
def _create_duplicate_application(data: FixtureData) -> Sequence[Step]:
    return [
        calls(
            call(
                "create_application",
                {
                    "program_id": str(data.id_of("program_id")),
                    "application_cycle": "2026/27",
                },
            )
        ),
        answer("这个项目你已经加过了。"),
    ]


@script("create_task")
def _create_task(data: FixtureData) -> Sequence[Step]:
    return [
        calls(
            call(
                "create_application_task",
                {
                    "application_id": str(data.id_of("application_id")),
                    "task": {
                        "task_type": "other",
                        "title": "联系导师要推荐信",
                    },
                },
            )
        ),
        answer(DONE),
    ]


@script("complete_cv_task")
def _complete_cv_task(data: FixtureData) -> Sequence[Step]:
    return [
        calls(
            call(
                "update_application_task",
                {
                    "task_id": str(data.id_of("cv_task_id")),
                    "update": {
                        "version": data.version_of("cv_task_version"),
                        "status": "done",
                    },
                },
            )
        ),
        answer(DONE),
    ]


def _status_call(
    data: FixtureData,
    target: str,
    *,
    version_offset: int = 0,
    call_id: str = "toolu_status",
) -> ModelToolCall:
    return call(
        "update_application_status",
        {
            "application_id": str(data.id_of("application_id")),
            "target_status": target,
            "version": data.version_of("application_version") + version_offset,
        },
        call_id=call_id,
    )


@script("move_to_ready")
def _move_to_ready(data: FixtureData) -> Sequence[Step]:
    return [calls(_status_call(data, "ready_to_submit")), answer(DONE)]


@script("move_to_preparing")
def _move_to_preparing(data: FixtureData) -> Sequence[Step]:
    return [calls(_status_call(data, "preparing")), answer(DONE)]


@script("move_with_stale_version")
def _move_with_stale_version(data: FixtureData) -> Sequence[Step]:
    return [
        calls(_status_call(data, "preparing", version_offset=5)),
        answer("版本已经变了，我重新读一下。"),
    ]


APPLICATION_CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        id="application_create_001",
        category=Category.APPLICATION,
        user_message="把项目 {program_id} 加进我 2026/27 的申请计划。",
        setup="program",
        script="create_application",
        expected_tools=frozenset({"create_application"}),
        expected_effect=EffectCheck(
            kind=EffectKind.APPLICATION_COUNT, params={"count": 1}
        ),
        real=True,
    ),
    EvaluationCase(
        id="application_duplicate_002",
        category=Category.APPLICATION,
        user_message="把项目 {program_id} 加进我 2026/27 的申请计划。",
        setup="shortlisted_application",
        script="create_duplicate_application",
        expected_tools=frozenset({"create_application"}),
        expected_error_codes=frozenset({ToolErrorCode.CONFLICT}),
        expected_effect=EffectCheck(
            kind=EffectKind.APPLICATION_COUNT, params={"count": 1}
        ),
        real=True,
        notes="选对工具但被业务规则拒绝不算路由错误，重复申请不能被创建。",
    ),
    EvaluationCase(
        id="application_create_task_003",
        category=Category.APPLICATION,
        user_message="在申请 {application_id} 下面加一条任务：联系导师要推荐信。",
        setup="shortlisted_application",
        script="create_task",
        expected_tools=frozenset({"create_application_task"}),
        expected_effect=EffectCheck(
            kind=EffectKind.TASK_STATUS,
            params={"task_type": "other", "status": "todo"},
        ),
    ),
    EvaluationCase(
        id="application_complete_task_004",
        category=Category.APPLICATION,
        user_message="我的简历写完了，把 CV 那条任务标记成完成。",
        setup="preparing_application",
        script="complete_cv_task",
        expected_tools=frozenset({"update_application_task"}),
        expected_effect=EffectCheck(
            kind=EffectKind.TASK_STATUS, params={"task_type": "cv", "status": "done"}
        ),
    ),
    EvaluationCase(
        id="application_not_ready_005",
        category=Category.APPLICATION,
        user_message="申请 {application_id}（version {application_version}）材料都好了，改成可以提交。",
        setup="preparing_application",
        script="move_to_ready",
        expected_tools=frozenset({"update_application_status"}),
        expected_error_codes=frozenset({ToolErrorCode.DOMAIN_INVALID}),
        expected_effect=EffectCheck(
            kind=EffectKind.APPLICATION_STATUS, params={"status": "preparing"}
        ),
        real=True,
        notes="申请准备度只由必要任务决定，不询问模型。",
    ),
    EvaluationCase(
        id="application_ready_006",
        category=Category.APPLICATION,
        user_message="申请 {application_id}（version {application_version}）材料都好了，改成可以提交。",
        setup="prepared_application",
        script="move_to_ready",
        expected_tools=frozenset({"update_application_status"}),
        expected_effect=EffectCheck(
            kind=EffectKind.APPLICATION_STATUS, params={"status": "ready_to_submit"}
        ),
    ),
    EvaluationCase(
        id="application_stale_version_007",
        category=Category.APPLICATION,
        user_message="申请 {application_id} 我开始准备材料了，改成 preparing。",
        setup="shortlisted_application",
        script="move_with_stale_version",
        expected_tools=frozenset({"update_application_status"}),
        expected_error_codes=frozenset({ToolErrorCode.CONFLICT}),
        expected_effect=EffectCheck(
            kind=EffectKind.APPLICATION_STATUS, params={"status": "shortlisted"}
        ),
    ),
)


@script("mark_submitted")
def _mark_submitted(data: FixtureData) -> Sequence[Step]:
    return [calls(_status_call(data, "submitted")), answer(DONE)]


@script("withdraw")
def _withdraw(data: FixtureData) -> Sequence[Step]:
    return [calls(_status_call(data, "withdrawn")), answer(DONE)]


@script("mark_offered")
def _mark_offered(data: FixtureData) -> Sequence[Step]:
    return [calls(_status_call(data, "offered")), answer(DONE)]


@script("mark_rejected")
def _mark_rejected(data: FixtureData) -> Sequence[Step]:
    return [calls(_status_call(data, "rejected")), answer(DONE)]


@script("read_and_submit_together")
def _read_and_submit_together(data: FixtureData) -> Sequence[Step]:
    return [
        calls(
            call("get_user_profile", {}, call_id="toolu_profile"),
            _status_call(data, "submitted", call_id="toolu_submit"),
        ),
        answer(DONE),
    ]


HITL_CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        id="hitl_submit_001",
        category=Category.HITL,
        user_message="申请 {application_id}（version {application_version}）我已经提交了，帮我更新状态。",
        setup="ready_application",
        script="mark_submitted",
        expected_tools=frozenset({"update_application_status"}),
        expected_final_status=AgentStatus.WAITING_CONFIRMATION,
        expect_confirmation=True,
        expected_effect=NO_CHANGE,
        real=True,
        notes="等待用户确认期间不能写入任何业务数据。",
    ),
    EvaluationCase(
        id="hitl_withdraw_002",
        category=Category.HITL,
        user_message="申请 {application_id}（version {application_version}）我不申了，撤销吧。",
        setup="shortlisted_application",
        script="withdraw",
        expected_tools=frozenset({"update_application_status"}),
        expected_final_status=AgentStatus.WAITING_CONFIRMATION,
        expect_confirmation=True,
        expected_effect=NO_CHANGE,
    ),
    EvaluationCase(
        id="hitl_offered_003",
        category=Category.HITL,
        user_message="申请 {application_id}（version {application_version}）给我发 offer 了。",
        setup="submitted_application",
        script="mark_offered",
        expected_tools=frozenset({"update_application_status"}),
        expected_final_status=AgentStatus.WAITING_CONFIRMATION,
        expect_confirmation=True,
        expected_effect=NO_CHANGE,
        notes="业务层允许直接记录录取，但 Agent 工具层要求确认，避免误写现实结果。",
    ),
    EvaluationCase(
        id="hitl_rejected_004",
        category=Category.HITL,
        user_message="申请 {application_id}（version {application_version}）被拒了。",
        setup="submitted_application",
        script="mark_rejected",
        expected_tools=frozenset({"update_application_status"}),
        expected_final_status=AgentStatus.WAITING_CONFIRMATION,
        expect_confirmation=True,
        expected_effect=NO_CHANGE,
    ),
    EvaluationCase(
        id="hitl_approve_005",
        category=Category.HITL,
        user_message="申请 {application_id}（version {application_version}）我已经提交了，帮我更新状态。",
        setup="ready_application",
        script="mark_submitted",
        expected_tools=frozenset({"update_application_status"}),
        expect_confirmation=True,
        resume=ResumeDecision.APPROVE,
        effect_at_pause=NO_CHANGE,
        expected_effect=EffectCheck(
            kind=EffectKind.APPLICATION_STATUS, params={"status": "submitted"}
        ),
        real=True,
    ),
    EvaluationCase(
        id="hitl_reject_006",
        category=Category.HITL,
        user_message="申请 {application_id}（version {application_version}）我已经提交了，帮我更新状态。",
        setup="ready_application",
        script="mark_submitted",
        expected_tools=frozenset({"update_application_status"}),
        expect_confirmation=True,
        resume=ResumeDecision.REJECT,
        effect_at_pause=NO_CHANGE,
        expected_effect=EffectCheck(
            kind=EffectKind.APPLICATION_STATUS, params={"status": "ready_to_submit"}
        ),
        real=True,
        notes="拒绝操作不代表运行失败；运行正常结束且不修改数据。",
    ),
    EvaluationCase(
        id="hitl_low_risk_no_prompt_007",
        category=Category.HITL,
        user_message="申请 {application_id}（version {application_version}）我开始准备材料了。",
        setup="shortlisted_application",
        script="move_to_preparing",
        expected_tools=frozenset({"update_application_status"}),
        expect_confirmation=False,
        expected_effect=EffectCheck(
            kind=EffectKind.APPLICATION_STATUS, params={"status": "preparing"}
        ),
        real=True,
        notes="低风险反例用于确认系统不会对所有写入都要求确认。",
    ),
    EvaluationCase(
        id="hitl_batch_pause_008",
        category=Category.HITL,
        user_message="看一下我的背景，然后把申请 {application_id}（version {application_version}）标记成已提交。",
        setup="ready_application",
        script="read_and_submit_together",
        expected_tools=frozenset({"update_application_status"}),
        forbidden_tools=frozenset({"get_user_profile"}),
        expected_final_status=AgentStatus.WAITING_CONFIRMATION,
        expect_confirmation=True,
        expected_effect=NO_CHANGE,
        notes="一项高风险调用会暂停整批任务，同轮只读调用也不能提前执行。",
    ),
)


@script("unknown_tool")
def _unknown_tool(data: FixtureData) -> Sequence[Step]:
    del data
    return [
        calls(call("list_scholarships", {"region": "singapore"})),
        answer("我没有查奖学金的工具。"),
    ]


@script("bad_cycle_then_retry")
def _bad_cycle_then_retry(data: FixtureData) -> Sequence[Step]:
    program_id = str(data.id_of("program_id"))

    def retry(results: Sequence[ToolResult]) -> ModelResponse:
        if error_code_of(results) != ToolErrorCode.INVALID_INPUT.value:
            return answer("没有需要重试的地方。")
        return calls(
            call(
                "create_application",
                {"program_id": program_id, "application_cycle": "2026/27"},
                call_id="toolu_retry",
            )
        )

    return [
        calls(
            call(
                "create_application",
                {"program_id": program_id, "application_cycle": "明年秋季"},
            )
        ),
        retry,
        answer(DONE),
    ]


@script("not_found_then_search")
def _not_found_then_search(data: FixtureData) -> Sequence[Step]:
    del data

    def recover(results: Sequence[ToolResult]) -> ModelResponse:
        if error_code_of(results) != ToolErrorCode.NOT_FOUND.value:
            return answer("没有需要重试的地方。")
        return calls(
            call(
                "search_programs",
                {"region": "singapore", "field_tags": ["ai"]},
                call_id="toolu_search",
            )
        )

    return [
        calls(call("get_program_requirements", {"program_id": MISSING_PROGRAM_ID})),
        recover,
        answer(DONE),
    ]


@script("duplicate_then_move_on")
def _duplicate_then_move_on(data: FixtureData) -> Sequence[Step]:
    def recover(results: Sequence[ToolResult]) -> ModelResponse:
        if error_code_of(results) != ToolErrorCode.CONFLICT.value:
            return answer("没有需要重试的地方。")
        return calls(_status_call(data, "preparing", call_id="toolu_status"))

    return [
        calls(
            call(
                "create_application",
                {
                    "program_id": str(data.id_of("program_id")),
                    "application_cycle": "2026/27",
                },
            )
        ),
        recover,
        answer(DONE),
    ]


@script("stale_version_then_retry")
def _stale_version_then_retry(data: FixtureData) -> Sequence[Step]:
    def retry(results: Sequence[ToolResult]) -> ModelResponse:
        if error_code_of(results) != ToolErrorCode.CONFLICT.value:
            return answer("没有需要重试的地方。")
        return calls(_status_call(data, "preparing", call_id="toolu_retry"))

    return [
        calls(_status_call(data, "preparing", version_offset=7)),
        retry,
        answer(DONE),
    ]


@script("search_over_budget")
def _search_over_budget(data: FixtureData) -> Sequence[Step]:
    del data
    return [_search(region="singapore", field_tags=["ai"]), answer(DONE)]


ERROR_RECOVERY_CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        id="recovery_unknown_tool_001",
        category=Category.ERROR_RECOVERY,
        user_message="帮我查一下有哪些奖学金可以申请。",
        setup="empty",
        script="unknown_tool",
        expected_error_codes=frozenset({ToolErrorCode.UNKNOWN_TOOL}),
        notes="未知工具应作为结构化错误返回模型，不能导致运行崩溃。",
    ),
    EvaluationCase(
        id="recovery_invalid_arguments_002",
        category=Category.ERROR_RECOVERY,
        user_message="把项目 {program_id} 加到我明年秋季入学的申请计划里。",
        setup="program",
        script="bad_cycle_then_retry",
        expected_tools=frozenset({"create_application"}),
        expected_error_codes=frozenset({ToolErrorCode.INVALID_INPUT}),
        expected_effect=EffectCheck(
            kind=EffectKind.APPLICATION_COUNT, params={"count": 1}
        ),
        notes="只有错误码真正传到下一轮后才会触发重试。",
    ),
    EvaluationCase(
        id="recovery_not_found_003",
        category=Category.ERROR_RECOVERY,
        user_message=(
            f"帮我看看项目 {MISSING_PROGRAM_ID} 的要求，"
            "找不到的话就推荐几个新加坡的 AI 项目。"
        ),
        setup="catalog",
        script="not_found_then_search",
        expected_tools=frozenset({"get_program_requirements", "search_programs"}),
        expected_tool_order=("get_program_requirements", "search_programs"),
        expected_error_codes=frozenset({ToolErrorCode.NOT_FOUND}),
        real=True,
    ),
    EvaluationCase(
        id="recovery_duplicate_004",
        category=Category.ERROR_RECOVERY,
        user_message="把项目 {program_id} 加进计划；如果已经加过了，就改成开始准备材料。",
        setup="shortlisted_application",
        script="duplicate_then_move_on",
        expected_tools=frozenset({"create_application", "update_application_status"}),
        expected_error_codes=frozenset({ToolErrorCode.CONFLICT}),
        expected_effect=EffectCheck(
            kind=EffectKind.APPLICATION_STATUS, params={"status": "preparing"}
        ),
    ),
    EvaluationCase(
        id="recovery_version_conflict_005",
        category=Category.ERROR_RECOVERY,
        user_message="申请 {application_id} 我开始准备材料了，用 version {application_version} 改。",
        setup="shortlisted_application",
        script="stale_version_then_retry",
        expected_tools=frozenset({"update_application_status"}),
        expected_error_codes=frozenset({ToolErrorCode.CONFLICT}),
        expected_effect=EffectCheck(
            kind=EffectKind.APPLICATION_STATUS, params={"status": "preparing"}
        ),
        notes="乐观锁冲突可以恢复，首次返回 CONFLICT 后才允许再次尝试。",
    ),
    EvaluationCase(
        id="recovery_budget_exceeded_006",
        category=Category.ERROR_RECOVERY,
        user_message="帮我找一下新加坡的人工智能硕士项目。",
        setup="catalog",
        script="search_over_budget",
        expected_tools=frozenset({"search_programs"}),
        expected_final_status=AgentStatus.BUDGET_EXCEEDED,
        budget=Budget(max_steps=1, max_tool_calls=10),
        notes="运行预算耗尽会停止后续步骤，但不会撤销已经完成的读取。",
    ),
)


DATASET: tuple[EvaluationCase, ...] = (
    *PROFILE_CASES,
    *PROGRAM_SEARCH_CASES,
    *PROGRAM_ANALYSIS_CASES,
    *APPLICATION_CASES,
    *HITL_CASES,
    *ERROR_RECOVERY_CASES,
)


def cases(
    *,
    category: Category | None = None,
    case_ids: Sequence[str] = (),
    real_only: bool = False,
) -> tuple[EvaluationCase, ...]:
    selected = DATASET
    if real_only:
        selected = tuple(case for case in selected if case.real)
    if category is not None:
        selected = tuple(case for case in selected if case.category is category)
    if case_ids:
        wanted = set(case_ids)
        selected = tuple(case for case in selected if case.id in wanted)
    return selected
