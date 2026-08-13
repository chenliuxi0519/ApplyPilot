"""Context Engineering 与长短期记忆。

A 短期指代 / B 跨重启 / C 跨 conversation 的长期 Profile /
D 临时条件不污染长期记忆 / E 历史过长时压缩。
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from langgraph.types import Command
from sqlmodel import Session

from app.agent.context import (
    SUMMARY_SYSTEM_PROMPT,
    ContextBudget,
    compose_system,
    plan_history,
    safe_cut,
)
from app.agent.graph import build_graph, new_state
from app.agent.recorder import InMemoryRunRecorder
from app.agent.trace import TraceEventType
from app.context import build_business_context
from app.core.config import settings
from app.modules.applications.models import ApplicationStatus
from app.modules.profiles import service as profile_service
from app.modules.profiles.models import (
    ProfileFieldSource,
    ProfileVerificationStatus,
)
from app.modules.profiles.schemas import UserProfileUpdate
from tests.agent.test_graph import (
    ScriptedModel,
    _answer,
    _call,
    _config,
    _context,
    _ready_application,
    _uses,
)
from tests.utils.application import create_application_for
from tests.utils.user import create_random_user

TEST_KEY = "applypilot-test-key-32-bytes!!!!"


@pytest.fixture(autouse=True)
def encryption_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHECKPOINT_ENCRYPTION_KEY", TEST_KEY)


class RecordingModel(ScriptedModel):
    """记下每次调用真正收到的 system 和 messages。"""

    def __init__(self, script: list[Any]) -> None:
        super().__init__(script)
        self.systems: list[str] = []
        self.histories: list[list[Any]] = []

        self.summary_calls = 0

    def complete(self, **kwargs: Any) -> Any:
        # 摘要调用用的是摘要系统提示，单独计数，不消耗剧本。
        # （verifier 的重写调用同样不带工具，靠 system 区分开。）
        if kwargs.get("system") == SUMMARY_SYSTEM_PROMPT:
            self.summary_calls += 1
            return _answer("早前聊过新加坡的计算机硕士，用户在挑项目。")
        self.systems.append(kwargs.get("system", ""))
        self.histories.append(list(kwargs.get("messages", [])))
        return super().complete(**kwargs)


def _write_profile(db: Session, user_id: Any, update: UserProfileUpdate) -> None:
    profile_service.update_profile(
        session=db,
        user_id=user_id,
        profile_update=update,
        source=ProfileFieldSource.USER_EXPLICIT,
        confidence=Decimal("1.000"),
        verification_status=ProfileVerificationStatus.USER_CONFIRMED,
    )


def _run(
    db: Session,
    user: Any,
    model: RecordingModel,
    conversation_id: str,
    message: str,
    saver: Any,
    budget: ContextBudget | None = None,
) -> dict[str, Any]:
    context = _context(db, user, model, InMemoryRunRecorder())
    context.business_context = lambda: build_business_context(
        session=db, user_id=user.id
    )
    if budget is not None:
        context.context_budget = budget
    return build_graph(saver).invoke(
        new_state(uuid.uuid4(), message, model),
        config=_config(user.id, conversation_id),
        context=context,
    )


# --------------------------------------------------------------------------
# 纯函数：裁剪必须产出合法历史
# --------------------------------------------------------------------------


def test_a_cut_never_splits_a_tool_call_from_its_result() -> None:
    messages = [
        {"role": "user", "content": "找项目"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "好"}]},
        {"role": "user", "content": "再问一句"},
    ]

    # 想从 tool_result 那条切开，实际必须退到合法边界
    assert safe_cut(messages, 2) == 0
    assert safe_cut(messages, 4) == 4


def test_a_cut_never_starts_the_history_with_an_assistant_message() -> None:
    messages = [
        {"role": "user", "content": "一"},
        {"role": "assistant", "content": [{"type": "text", "text": "二"}]},
        {"role": "user", "content": "三"},
    ]

    assert messages[safe_cut(messages, 1)]["role"] == "user"
    assert messages[safe_cut(messages, 2)]["role"] == "user"


def test_a_short_history_is_never_summarized() -> None:
    messages = [{"role": "user", "content": f"m{i}"} for i in range(10)]

    summarized, cut = plan_history(messages, 0, ContextBudget())

    assert summarized == 0
    assert cut == 0


def test_a_long_history_triggers_one_summary() -> None:
    messages = [{"role": "user", "content": f"m{i}"} for i in range(40)]
    budget = ContextBudget(keep_recent=6, summary_threshold=10)

    summarized, cut = plan_history(messages, 0, budget)

    assert summarized == cut > 0
    assert len(messages) - cut <= 6
    # 已经摘要过之后，历史不再增长就不会重复摘要
    assert plan_history(messages, summarized, budget)[0] == summarized


def test_the_summary_is_marked_as_not_authoritative() -> None:
    system = compose_system(
        "SYSTEM", "[USER_PROFILE]\nielts_overall: 7.5", "聊过新加坡"
    )

    assert "[CONVERSATION_SUMMARY]" in system
    assert "以 [USER_PROFILE]" in system
    assert system.index("[USER_PROFILE]") < system.index("[CONVERSATION_SUMMARY]")


# --------------------------------------------------------------------------
# 业务事实块
# --------------------------------------------------------------------------


def test_the_profile_block_only_uses_real_schema_fields(db: Session) -> None:
    user = create_random_user(db)
    _write_profile(
        db,
        user.id,
        UserProfileUpdate(
            undergraduate_major="计算机科学",
            ielts_overall=Decimal("7.5"),
            target_regions=["新加坡"],
        ),
    )

    context, fields = build_business_context(session=db, user_id=user.id)

    assert "[USER_PROFILE]" in context
    assert "ielts_overall: 7.5" in context
    assert "undergraduate_major: 计算机科学" in context
    assert "target_regions: 新加坡" in context
    assert fields == 3


def test_an_empty_profile_says_so_instead_of_inventing_fields(db: Session) -> None:
    user = create_random_user(db)

    context, fields = build_business_context(session=db, user_id=user.id)

    assert fields == 0
    assert "尚未填写个人档案" in context
    assert "还没有在跟进的申请" in context


def test_the_application_block_carries_the_current_status(db: Session) -> None:
    user, application, _ = create_application_for(db)

    context, _ = build_business_context(session=db, user_id=user.id)

    assert "[CURRENT_APPLICATION_CONTEXT]" in context
    assert f"application_id={application.id}" in context
    assert f"status={application.status.value}" in context
    assert "required_done=" in context


# --------------------------------------------------------------------------
# Test A：同一 conversation 的短期指代
# --------------------------------------------------------------------------


def test_the_next_turn_can_refer_back_to_the_previous_one(
    db: Session, checkpointer: Any
) -> None:
    user = create_random_user(db)
    conversation_id = f"c-{uuid.uuid4().hex}"

    first = RecordingModel([_answer("NUS CS 是新加坡国立大学的计算机硕士。")])
    _run(db, user, first, conversation_id, "帮我看看 NUS CS。", checkpointer)

    second = RecordingModel([_answer("它的雅思要求是 6.5。")])
    context = _context(db, user, second, InMemoryRunRecorder())
    build_graph(checkpointer).invoke(
        {"messages": [second.user_message("它雅思要求多少？")]},
        config=_config(user.id, conversation_id),
        context=context,
    )

    history = second.histories[0]
    assert any("NUS CS" in str(message) for message in history)
    assert "它雅思要求多少？" in str(history[-1])


# --------------------------------------------------------------------------
# Test B：跨后端重启
# --------------------------------------------------------------------------


def test_the_context_survives_a_backend_restart(db: Session) -> None:
    from app.agent.checkpointer import open_checkpointer

    user = create_random_user(db)
    conversation_id = f"c-{uuid.uuid4().hex}"

    with open_checkpointer() as saver:
        saver.setup()
        first = RecordingModel([_answer("NUS CS 和 NTU CS 各有优势。")])
        _run(db, user, first, conversation_id, "帮我比较 NUS CS 和 NTU CS。", saver)

    # 全新的 checkpointer 和图，等价于重启后端
    with open_checkpointer() as saver:
        second = RecordingModel([_answer("NTU CS 的学费大约是 …")])
        context = _context(db, user, second, InMemoryRunRecorder())
        build_graph(saver).invoke(
            {"messages": [second.user_message("那第二个学费呢？")]},
            config=_config(user.id, conversation_id),
            context=context,
        )
        saver.delete_thread(f"{user.id}:{conversation_id}")

    history = second.histories[0]
    assert any("NTU CS" in str(message) for message in history)
    assert len(history) >= 3


# --------------------------------------------------------------------------
# Test C：跨 conversation 的长期 Profile
# --------------------------------------------------------------------------


def test_a_new_conversation_reads_the_profile_but_not_the_old_chat(
    db: Session, checkpointer: Any
) -> None:
    user = create_random_user(db)
    conversation_a = f"c-{uuid.uuid4().hex}"
    conversation_b = f"c-{uuid.uuid4().hex}"

    # Conversation A：通过既有工具把雅思写进正式档案
    writer = RecordingModel(
        [
            _uses(_call("update_user_profile", {"ielts_overall": 7.5})),
            _answer("已经把你的雅思更新为 7.5。"),
        ]
    )
    paused = _run(
        db, user, writer, conversation_a, "我的雅思已经 7.5 了。", checkpointer
    )
    # 改雅思属于高风险写入，先暂停等确认——这条链路本身也在这里被验证一次
    assert "__interrupt__" in paused
    context = _context(db, user, writer, InMemoryRunRecorder())
    context.business_context = lambda: build_business_context(
        session=db, user_id=user.id
    )
    build_graph(checkpointer).invoke(
        Command(resume={"approved": True}),
        config=_config(user.id, conversation_a),
        context=context,
    )

    profile = profile_service.get_profile(session=db, user_id=user.id)
    assert profile is not None and profile.ielts_overall == Decimal("7.5")

    # Conversation B：全新 thread
    reader = RecordingModel([_answer("根据你的背景，我推荐这几个项目。")])
    _run(db, user, reader, conversation_b, "按我的背景推荐项目。", checkpointer)

    system = reader.systems[0]
    history = reader.histories[0]

    # 长期事实来自 PostgreSQL
    assert "ielts_overall: 7.5" in system
    # 但拿不到 A 的聊天记录
    assert len(history) == 1
    assert "雅思已经 7.5" not in str(history)


def test_the_profile_block_reflects_a_change_made_in_the_same_turn(
    db: Session, checkpointer: Any
) -> None:
    """工具改完档案，下一次模型调用就应该看到新值。"""
    user = create_random_user(db)
    model = RecordingModel(
        [
            _uses(_call("update_user_profile", {"ielts_overall": 7.0})),
            _answer("更新好了。"),
        ]
    )

    conversation_id = f"c-{uuid.uuid4().hex}"
    _run(db, user, model, conversation_id, "我雅思 7 分", checkpointer)
    context = _context(db, user, model, InMemoryRunRecorder())
    context.business_context = lambda: build_business_context(
        session=db, user_id=user.id
    )
    build_graph(checkpointer).invoke(
        Command(resume={"approved": True}),
        config=_config(user.id, conversation_id),
        context=context,
    )

    # 档案块的形式是 "字段: 值"，第一轮还没写入所以不该出现
    assert "ielts_overall: " not in model.systems[0]
    assert "ielts_overall: 7" in model.systems[1]


# --------------------------------------------------------------------------
# Test D：临时条件不写进长期档案
# --------------------------------------------------------------------------


def test_a_temporary_preference_never_reaches_the_profile(
    db: Session, checkpointer: Any
) -> None:
    user = create_random_user(db)
    conversation_a = f"c-{uuid.uuid4().hex}"

    model = RecordingModel([_answer("好的，这次只看新加坡的项目。")])
    _run(db, user, model, conversation_a, "这次只考虑新加坡。", checkpointer)

    # 没有调用任何写工具，档案就不该被创建或改动
    profile = profile_service.get_profile(session=db, user_id=user.id)
    assert profile is None or not profile.target_regions

    # 新 conversation 看不到这条临时条件
    fresh = RecordingModel([_answer("我可以帮你看看别的地区。")])
    _run(db, user, fresh, f"c-{uuid.uuid4().hex}", "推荐项目", checkpointer)

    assert "新加坡" not in fresh.systems[0]
    assert len(fresh.histories[0]) == 1


def test_only_an_explicit_tool_call_updates_the_profile(
    db: Session, checkpointer: Any
) -> None:
    user = create_random_user(db)
    model = RecordingModel(
        [
            _uses(_call("update_user_profile", {"target_regions": ["新加坡"]})),
            _answer("已经把目标地区记为新加坡。"),
        ]
    )

    _run(db, user, model, f"c-{uuid.uuid4().hex}", "以后都只看新加坡", checkpointer)

    profile = profile_service.get_profile(session=db, user_id=user.id)
    assert profile is not None and profile.target_regions == ["新加坡"]


# --------------------------------------------------------------------------
# Test E：历史过长
# --------------------------------------------------------------------------


def test_a_long_history_is_compressed_but_recent_turns_stay_verbatim(
    db: Session, checkpointer: Any
) -> None:
    user = create_random_user(db)
    conversation_id = f"c-{uuid.uuid4().hex}"
    budget = ContextBudget(keep_recent=4, summary_threshold=6)

    # 先堆出一段长历史
    for index in range(6):
        model = RecordingModel([_answer(f"第 {index} 轮回答。")])
        context = _context(db, user, model, InMemoryRunRecorder())
        context.business_context = lambda: build_business_context(
            session=db, user_id=user.id
        )
        context.context_budget = budget
        payload: Any = (
            new_state(uuid.uuid4(), "第 0 轮问题：我想申请新加坡的计算机硕士。", model)
            if index == 0
            else {"messages": [model.user_message(f"第 {index} 轮问题。")]}
        )
        build_graph(checkpointer).invoke(
            payload, config=_config(user.id, conversation_id), context=context
        )

    # 再来一轮，这时应该触发摘要
    last = RecordingModel([_answer("最后一轮回答。")])
    context = _context(db, user, last, InMemoryRunRecorder())
    context.business_context = lambda: build_business_context(
        session=db, user_id=user.id
    )
    context.context_budget = budget
    result = build_graph(checkpointer).invoke(
        {"messages": [last.user_message("最后一轮问题。")]},
        config=_config(user.id, conversation_id),
        context=context,
    )

    # 摘要调用 + 正式调用
    assert last.summary_calls >= 1
    assert result["summary"] is not None
    assert result["summarized_count"] > 0

    sent = last.histories[-1]
    # 模型输入被裁剪，但 checkpoint 里保留完整历史
    assert len(sent) < len(result["messages"])
    assert "最后一轮问题。" in str(sent[-1])

    # trace 里记下了数量，但没有内容
    model_events = [
        event for event in result["trace"] if event["event_type"] == "model_request"
    ]
    assert model_events[-1]["history_count"] == len(sent)
    assert model_events[-1]["estimated_tokens"] > 0
    assert any(event["summarized"] for event in model_events)


def test_the_trace_records_counts_but_never_content(
    db: Session, checkpointer: Any
) -> None:
    user, application = _ready_application(db)
    model = RecordingModel([_answer("好的。")])

    result = _run(
        db, user, model, f"c-{uuid.uuid4().hex}", "我的申请怎么样了？", checkpointer
    )

    event = next(
        e for e in result["trace"] if e["event_type"] == TraceEventType.MODEL_REQUEST
    )
    assert event["history_count"] == 1
    assert event["profile_fields"] == 0
    assert event["summarized"] is False

    serialized = str(result["trace"])
    assert "我的申请怎么样了" not in serialized
    assert str(application.id) not in serialized


def test_the_business_facts_win_over_the_summary(
    db: Session, checkpointer: Any
) -> None:
    """摘要说的和数据库冲突时，系统提示明确要求以数据库为准。"""
    user, application = _ready_application(db)
    _write_profile(db, user.id, UserProfileUpdate(ielts_overall=Decimal("7.5")))
    model = RecordingModel([_answer("好的。")])

    _run(db, user, model, f"c-{uuid.uuid4().hex}", "我的情况如何？", checkpointer)

    system = model.systems[0]
    assert "ielts_overall: 7.5" in system
    assert f"status={application.status.value}" in system
    assert ApplicationStatus.READY_TO_SUBMIT.value in system


@pytest.fixture
def checkpointer() -> Any:
    from app.agent.checkpointer import open_checkpointer

    with open_checkpointer() as saver:
        saver.setup()
        yield saver
