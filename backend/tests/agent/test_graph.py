"""LangGraph 编排的三个核心场景。

A. 普通工具调用
B. 高风险写入暂停 → 批准 → 恢复
C. 暂停后后端重启 → 批准 → 从 PostgreSQL checkpoint 恢复
"""

import uuid
from typing import Any

import pytest
from langgraph.types import Command
from sqlmodel import Session, col, select

from app.agent.budget import Budget
from app.agent.checkpointer import open_checkpointer
from app.agent.graph import AgentRuntimeContext, build_graph, new_state
from app.agent.model import ModelResponse, ModelStopReason, ModelToolCall
from app.agent.recorder import InMemoryRunRecorder
from app.agent.state import AgentStatus
from app.agent.trace import TraceEventType
from app.core.config import settings
from app.modules.applications.models import Application, ApplicationStatus
from app.tools import build_default_registry
from tests.utils.application import (
    complete_required_tasks,
    create_application_for,
    move_to,
)
from tests.utils.program import create_random_program

TEST_KEY = "applypilot-test-key-32-bytes!!!!"


@pytest.fixture(autouse=True)
def encryption_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHECKPOINT_ENCRYPTION_KEY", TEST_KEY)


class ScriptedModel:
    """按剧本回答的模型，让编排逻辑可以确定性地测。"""

    def __init__(self, script: list[ModelResponse]) -> None:
        self._script = script
        self.calls = 0

    def complete(self, **kwargs: Any) -> ModelResponse:
        del kwargs
        if self.calls >= len(self._script):
            raise AssertionError("图比剧本多要了一步")
        response = self._script[self.calls]
        self.calls += 1
        return response

    def user_message(self, text: str) -> Any:
        return {"role": "user", "content": text}

    def tool_result_message(self, results: Any) -> Any:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": r.call_id, "content": r.status}
                for r in results
            ],
        }


def _answer(text: str) -> ModelResponse:
    return ModelResponse(
        stop_reason=ModelStopReason.END_TURN,
        text=text,
        tool_calls=(),
        assistant_message={
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    )


def _uses(*calls: ModelToolCall) -> ModelResponse:
    return ModelResponse(
        stop_reason=ModelStopReason.TOOL_USE,
        text=None,
        tool_calls=calls,
        assistant_message={
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                for c in calls
            ],
        },
    )


def _call(
    name: str, arguments: dict[str, Any], call_id: str = "toolu_1"
) -> ModelToolCall:
    return ModelToolCall(id=call_id, name=name, arguments=arguments)


def _context(
    db: Session, user: Any, model: ScriptedModel, recorder: InMemoryRunRecorder
) -> AgentRuntimeContext:
    return AgentRuntimeContext(
        user_id=user.id,
        is_superuser=user.is_superuser,
        session=db,
        model=model,
        registry=build_default_registry(),
        recorder=recorder,
        budget=Budget(),
    )


def _config(user_id: uuid.UUID, conversation_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": f"{user_id}:{conversation_id}"}}


@pytest.fixture
def conversation_id() -> str:
    return f"c-{uuid.uuid4().hex}"


# --------------------------------------------------------------------------
# A. 普通工具调用
# --------------------------------------------------------------------------


def test_a_read_tool_runs_without_stopping(db: Session, conversation_id: str) -> None:
    user, _, _ = create_application_for(db)
    program = create_random_program(db)
    model = ScriptedModel(
        [
            _uses(_call("search_programs", {"program_id": str(program.id)})),
            _answer("给你找到了这个项目。"),
        ]
    )
    recorder = InMemoryRunRecorder()
    run_id = uuid.uuid4()

    with open_checkpointer() as saver:
        saver.setup()
        graph = build_graph(saver)
        result = graph.invoke(
            new_state(run_id, "帮我搜一下项目", model),
            config=_config(user.id, conversation_id),
            context=_context(db, user, model, recorder),
        )
        saver.delete_thread(f"{user.id}:{conversation_id}")

    assert "__interrupt__" not in result
    assert result["status"] == AgentStatus.COMPLETED.value
    assert result["final_answer"] == "给你找到了这个项目。"
    assert result["tool_call_count"] == 1
    assert model.calls == 2

    kinds = [event["event_type"] for event in result["trace"]]
    assert TraceEventType.TOOL_CALL.value in kinds
    assert TraceEventType.HUMAN_CONFIRMATION_REQUIRED.value not in kinds
    assert result["trace"][-1]["final_status"] == AgentStatus.COMPLETED.value


def test_a_bad_argument_comes_back_to_the_model_as_an_error(
    db: Session, conversation_id: str
) -> None:
    """参数校验仍由 harness 负责，节点不自己判断。"""
    user, _, _ = create_application_for(db)
    model = ScriptedModel(
        [
            _uses(_call("search_programs", {"degree_type": "不存在的学位"})),
            _answer("换个条件再试试。"),
        ]
    )

    with open_checkpointer() as saver:
        saver.setup()
        result = build_graph(saver).invoke(
            new_state(uuid.uuid4(), "搜索", model),
            config=_config(user.id, conversation_id),
            context=_context(db, user, model, InMemoryRunRecorder()),
        )
        saver.delete_thread(f"{user.id}:{conversation_id}")

    tool_events = [e for e in result["trace"] if e["event_type"] == "tool_call"]
    assert tool_events and tool_events[0]["tool_result_status"] == "error"
    assert result["status"] == AgentStatus.COMPLETED.value


# --------------------------------------------------------------------------
# B. 高风险写入：暂停 → 批准 → 恢复
# --------------------------------------------------------------------------


def _ready_application(db: Session) -> tuple[Any, Application]:
    """把申请推到 ready_to_submit：标记提交是从这个状态出发的高风险操作。"""
    user, application, _ = create_application_for(db)
    application = move_to(
        db, user=user, application=application, target=ApplicationStatus.PREPARING
    )
    complete_required_tasks(db, user=user, application_id=application.id)
    db.refresh(application)
    application = move_to(
        db,
        user=user,
        application=application,
        target=ApplicationStatus.READY_TO_SUBMIT,
    )
    return user, application


def _submit_script(application: Application) -> list[ModelResponse]:
    return [
        _uses(
            _call(
                "update_application_status",
                {
                    "application_id": str(application.id),
                    "target_status": "submitted",
                    "version": application.version,
                },
            )
        ),
        _answer("已经帮你标记为已提交。"),
    ]


def test_a_high_risk_write_pauses_and_changes_nothing(
    db: Session, conversation_id: str
) -> None:
    user, application = _ready_application(db)
    model = ScriptedModel(_submit_script(application))

    with open_checkpointer() as saver:
        saver.setup()
        result = build_graph(saver).invoke(
            new_state(uuid.uuid4(), "标记为已提交", model),
            config=_config(user.id, conversation_id),
            context=_context(db, user, model, InMemoryRunRecorder()),
        )
        saver.delete_thread(f"{user.id}:{conversation_id}")

    assert "__interrupt__" in result
    assert result["status"] == AgentStatus.WAITING_CONFIRMATION.value
    assert result["pending_confirmation"]["tool_name"] == "update_application_status"
    assert result["pending_confirmation"]["permission_level"] == "high_risk_write"
    assert model.calls == 1  # 停在确认前，没有继续问模型

    db.refresh(application)
    assert application.status is not ApplicationStatus.SUBMITTED


def test_approving_applies_the_change_and_finishes(
    db: Session, conversation_id: str
) -> None:
    user, application = _ready_application(db)
    model = ScriptedModel(_submit_script(application))
    recorder = InMemoryRunRecorder()

    with open_checkpointer() as saver:
        saver.setup()
        graph = build_graph(saver)
        config = _config(user.id, conversation_id)
        graph.invoke(
            new_state(uuid.uuid4(), "标记为已提交", model),
            config=config,
            context=_context(db, user, model, recorder),
        )
        result = graph.invoke(
            Command(resume={"approved": True}),
            config=config,
            context=_context(db, user, model, recorder),
        )
        saver.delete_thread(f"{user.id}:{conversation_id}")

    assert result["status"] == AgentStatus.COMPLETED.value
    assert result["final_answer"] == "已经帮你标记为已提交。"

    db.refresh(application)
    assert application.status is ApplicationStatus.SUBMITTED

    kinds = [event["event_type"] for event in result["trace"]]
    assert kinds.count(TraceEventType.HUMAN_CONFIRMATION_REQUIRED.value) == 1
    assert kinds.count(TraceEventType.HUMAN_APPROVED.value) == 1
    assert TraceEventType.RUN_RESUMED.value in kinds


def test_rejecting_leaves_the_application_alone(
    db: Session, conversation_id: str
) -> None:
    user, application = _ready_application(db)
    model = ScriptedModel(_submit_script(application))

    with open_checkpointer() as saver:
        saver.setup()
        graph = build_graph(saver)
        config = _config(user.id, conversation_id)
        context = _context(db, user, model, InMemoryRunRecorder())
        graph.invoke(
            new_state(uuid.uuid4(), "标记为已提交", model),
            config=config,
            context=context,
        )
        result = graph.invoke(
            Command(resume={"approved": False}), config=config, context=context
        )
        saver.delete_thread(f"{user.id}:{conversation_id}")

    db.refresh(application)
    assert application.status is not ApplicationStatus.SUBMITTED
    assert result["status"] == AgentStatus.COMPLETED.value
    assert TraceEventType.HUMAN_REJECTED.value in [
        event["event_type"] for event in result["trace"]
    ]
    # 拒绝不消耗工具预算
    assert result["tool_call_count"] == 0


# --------------------------------------------------------------------------
# C. 暂停后重启后端 → 批准 → 恢复
# --------------------------------------------------------------------------


def test_a_paused_run_survives_a_backend_restart(
    db: Session, conversation_id: str
) -> None:
    """暂停后把进程内的一切都丢掉，只靠 PostgreSQL 里的 checkpoint 恢复。"""
    user, application = _ready_application(db)
    config = _config(user.id, conversation_id)

    # ---- 重启前：产生一次暂停 ----
    first_model = ScriptedModel(_submit_script(application))
    with open_checkpointer() as saver:
        saver.setup()
        paused = build_graph(saver).invoke(
            new_state(uuid.uuid4(), "标记为已提交", first_model),
            config=config,
            context=_context(db, user, first_model, InMemoryRunRecorder()),
        )
    assert "__interrupt__" in paused

    db.refresh(application)
    assert application.status is not ApplicationStatus.SUBMITTED

    # ---- 重启：全新的 checkpointer、全新的图、全新的模型对象 ----
    second_model = ScriptedModel([_answer("已经帮你标记为已提交。")])
    with open_checkpointer() as saver:
        graph = build_graph(saver)
        resumed = graph.invoke(
            Command(resume={"approved": True}),
            config=config,
            context=_context(db, user, second_model, InMemoryRunRecorder()),
        )
        saver.delete_thread(f"{user.id}:{conversation_id}")

    assert resumed["status"] == AgentStatus.COMPLETED.value
    assert resumed["final_answer"] == "已经帮你标记为已提交。"

    db.refresh(application)
    assert application.status is ApplicationStatus.SUBMITTED

    # 重启前写下的对话历史仍然在
    assert len(resumed["messages"]) >= len(paused["messages"])
    assert resumed["run_id"] == paused["run_id"]


def test_another_user_cannot_reach_the_thread(
    db: Session, conversation_id: str
) -> None:
    """thread_id 带用户前缀，别人的 conversation_id 落到自己的命名空间。"""
    user, application, _ = create_application_for(db)
    other, _, _ = create_application_for(db)
    model = ScriptedModel(_submit_script(application))

    with open_checkpointer() as saver:
        saver.setup()
        graph = build_graph(saver)
        graph.invoke(
            new_state(uuid.uuid4(), "标记为已提交", model),
            config=_config(user.id, conversation_id),
            context=_context(db, user, model, InMemoryRunRecorder()),
        )

        # 另一个用户拿同样的 conversation_id，落到的是空 thread
        assert saver.get_tuple(_config(other.id, conversation_id)) is None
        assert saver.get_tuple(_config(user.id, conversation_id)) is not None
        saver.delete_thread(f"{user.id}:{conversation_id}")

    db.refresh(application)
    assert application.status is not ApplicationStatus.SUBMITTED


def test_the_run_is_recorded_as_waiting_before_it_pauses(
    db: Session, conversation_id: str
) -> None:
    """暂停时运行记录必须已经落库，否则重启后没人知道它在等确认。"""
    user, application = _ready_application(db)
    model = ScriptedModel(_submit_script(application))
    recorder = InMemoryRunRecorder()

    with open_checkpointer() as saver:
        saver.setup()
        build_graph(saver).invoke(
            new_state(uuid.uuid4(), "标记为已提交", model),
            config=_config(user.id, conversation_id),
            context=_context(db, user, model, recorder),
        )
        saver.delete_thread(f"{user.id}:{conversation_id}")

    assert [status for _, status in recorder.finished] == [
        AgentStatus.WAITING_CONFIRMATION.value
    ]
    assert TraceEventType.HUMAN_CONFIRMATION_REQUIRED.value in recorder.event_types()


def test_no_application_belongs_to_the_wrong_user(db: Session) -> None:
    """跨用户隔离仍由领域层保证，图不绕过它。"""
    user, _, _ = create_application_for(db)
    other, application, _ = create_application_for(db)
    conversation_id = f"c-{uuid.uuid4().hex}"
    model = ScriptedModel(_submit_script(application))

    with open_checkpointer() as saver:
        saver.setup()
        graph = build_graph(saver)
        config = _config(user.id, conversation_id)
        context = _context(db, user, model, InMemoryRunRecorder())
        graph.invoke(
            new_state(uuid.uuid4(), "标记为已提交", model),
            config=config,
            context=context,
        )
        result = graph.invoke(
            Command(resume={"approved": True}), config=config, context=context
        )
        saver.delete_thread(f"{user.id}:{conversation_id}")

    # 批准了，但那份申请不属于当前用户，领域层拒绝
    db.refresh(application)
    assert application.status is not ApplicationStatus.SUBMITTED
    tool_events = [e for e in result["trace"] if e["event_type"] == "tool_call"]
    assert tool_events and tool_events[-1]["tool_result_status"] == "error"


def test_the_thread_holds_the_conversation_for_a_follow_up(
    db: Session, conversation_id: str
) -> None:
    """同一个 thread 的第二轮能看到第一轮的消息。"""
    user, _, _ = create_application_for(db)
    config = _config(user.id, conversation_id)

    first = ScriptedModel([_answer("你好。")])
    with open_checkpointer() as saver:
        saver.setup()
        graph = build_graph(saver)
        one = graph.invoke(
            new_state(uuid.uuid4(), "你好", first),
            config=config,
            context=_context(db, user, first, InMemoryRunRecorder()),
        )

        second = ScriptedModel([_answer("刚才你说了你好。")])
        two = graph.invoke(
            {"messages": [second.user_message("我刚才说了什么？")]},
            config=config,
            context=_context(db, user, second, InMemoryRunRecorder()),
        )
        saver.delete_thread(f"{user.id}:{conversation_id}")

    assert len(two["messages"]) > len(one["messages"])
    assert two["messages"][0] == one["messages"][0]


def test_leftover_threads_are_cleaned_up(db: Session) -> None:
    """确认测试自己不留 thread。"""
    user, _, _ = create_application_for(db)
    conversation_id = f"c-{uuid.uuid4().hex}"
    model = ScriptedModel([_answer("好的。")])

    with open_checkpointer() as saver:
        saver.setup()
        build_graph(saver).invoke(
            new_state(uuid.uuid4(), "你好", model),
            config=_config(user.id, conversation_id),
            context=_context(db, user, model, InMemoryRunRecorder()),
        )
        saver.delete_thread(f"{user.id}:{conversation_id}")
        assert saver.get_tuple(_config(user.id, conversation_id)) is None

    rows = db.exec(select(Application).where(col(Application.user_id) == user.id)).all()
    assert rows is not None
