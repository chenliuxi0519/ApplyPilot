"""graph 引擎走完整 HTTP 链路，响应结构必须和 loop 引擎一致。

前端只认 /agent/chat 和 /agent/runs/{id}/approve|reject 这套协议，
换引擎不能让它感知到任何变化。
"""

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.agent import checkpointer as checkpointer_module
from app.agent.checkpointer import open_checkpointer
from app.agent.model import ModelResponse, ModelToolCall
from app.api.routes import agent_chat
from app.core.config import settings
from app.main import app
from app.models import User
from app.modules.applications.models import Application, ApplicationStatus
from tests.agent.test_graph import (
    ScriptedModel,
    _answer,
    _call,
    _ready_application,
    _uses,
)
from tests.utils.user import authentication_token_from_email

CHAT_URL = f"{settings.API_V1_STR}/agent/chat"
TEST_KEY = "applypilot-test-key-32-bytes!!!!"


@pytest.fixture(autouse=True)
def graph_engine(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    monkeypatch.setattr(settings, "AGENT_ENGINE", "graph")
    monkeypatch.setattr(settings, "CHECKPOINT_ENCRYPTION_KEY", TEST_KEY)
    with open_checkpointer() as saver:
        saver.setup()
    _restart_backend()
    yield
    _restart_backend()
    app.dependency_overrides.pop(agent_chat.get_model_client, None)


def _restart_backend() -> None:
    """丢掉进程内缓存的图和连接池，等价于重启一次后端。"""
    agent_chat._graph = None
    checkpointer_module.close_checkpointer()


def _script(*responses: ModelResponse) -> ScriptedModel:
    model = ScriptedModel(list(responses))
    app.dependency_overrides[agent_chat.get_model_client] = lambda: model
    return model


def _headers(client: TestClient, db: Session, user: User) -> dict[str, str]:
    return authentication_token_from_email(client=client, email=user.email, db=db)


def _submit_call(application: Application) -> ModelToolCall:
    return _call(
        "update_application_status",
        {
            "application_id": str(application.id),
            "target_status": "submitted",
            "version": application.version,
        },
        call_id="toolu_submit",
    )


def _runs_url(run_id: str, action: str) -> str:
    return f"{settings.API_V1_STR}/agent/runs/{run_id}/{action}"


# --------------------------------------------------------------------------
# A. 普通工具调用
# --------------------------------------------------------------------------


def test_a_plain_answer_comes_back_with_a_run_id(
    client: TestClient, db: Session
) -> None:
    user, _ = _ready_application(db)
    _script(_answer("你好，我可以帮你规划申请。"))

    body = client.post(
        CHAT_URL,
        headers=_headers(client, db, user),
        json={"message": "你好"},
    ).json()

    assert body["status"] == "completed"
    assert body["answer"] == "你好，我可以帮你规划申请。"
    assert uuid.UUID(body["run_id"])
    assert body["conversation_id"].startswith("c-")
    assert body["confirmation"] is None


def test_the_response_shape_matches_the_loop_engine(
    client: TestClient, db: Session
) -> None:
    user, _ = _ready_application(db)
    _script(_answer("好的。"))

    body = client.post(
        CHAT_URL, headers=_headers(client, db, user), json={"message": "你好"}
    ).json()

    assert set(body) == {
        "run_id",
        "conversation_id",
        "status",
        "answer",
        "confirmation",
        "tool_trace",
        "ui_events",
        "steps",
        "tool_calls",
        "error",
    }


def test_a_follow_up_keeps_the_same_conversation(
    client: TestClient, db: Session
) -> None:
    user, _ = _ready_application(db)
    headers = _headers(client, db, user)
    _script(_answer("第一轮。"))
    first = client.post(CHAT_URL, headers=headers, json={"message": "你好"}).json()

    _script(_answer("第二轮。"))
    second = client.post(
        CHAT_URL,
        headers=headers,
        json={"message": "再问一句", "conversation_id": first["conversation_id"]},
    ).json()

    assert second["conversation_id"] == first["conversation_id"]
    assert second["run_id"] != first["run_id"]


# --------------------------------------------------------------------------
# B. 高风险写入：暂停 → 批准
# --------------------------------------------------------------------------


def test_a_high_risk_write_pauses_and_changes_nothing(
    client: TestClient, db: Session
) -> None:
    user, application = _ready_application(db)
    _script(_uses(_submit_call(application)))

    body = client.post(
        CHAT_URL, headers=_headers(client, db, user), json={"message": "标记为已提交"}
    ).json()

    assert body["status"] == "waiting_confirmation"
    assert body["confirmation"]["tool_name"] == "update_application_status"
    assert body["confirmation"]["permission_level"] == "high_risk_write"
    assert body["confirmation"]["summary"]["target_status"] == "submitted"
    assert body["confirmation"]["summary"]["program_label"]

    db.refresh(application)
    assert application.status is ApplicationStatus.READY_TO_SUBMIT


def test_approving_applies_the_change(client: TestClient, db: Session) -> None:
    user, application = _ready_application(db)
    headers = _headers(client, db, user)
    _script(_uses(_submit_call(application)), _answer("已经标记为已提交。"))

    paused = client.post(
        CHAT_URL, headers=headers, json={"message": "标记为已提交"}
    ).json()
    resumed = client.post(_runs_url(paused["run_id"], "approve"), headers=headers)

    assert resumed.status_code == 200
    body = resumed.json()
    assert body["status"] == "completed"
    assert body["answer"] == "已经标记为已提交。"
    assert body["run_id"] == paused["run_id"]

    db.refresh(application)
    assert application.status is ApplicationStatus.SUBMITTED


def test_rejecting_leaves_the_application_alone(
    client: TestClient, db: Session
) -> None:
    user, application = _ready_application(db)
    headers = _headers(client, db, user)
    _script(_uses(_submit_call(application)), _answer("那就先不提交。"))

    paused = client.post(
        CHAT_URL, headers=headers, json={"message": "标记为已提交"}
    ).json()
    body = client.post(_runs_url(paused["run_id"], "reject"), headers=headers).json()

    assert body["status"] == "completed"
    db.refresh(application)
    assert application.status is ApplicationStatus.READY_TO_SUBMIT


def test_another_user_cannot_approve_a_pending_run(
    client: TestClient, db: Session
) -> None:
    user, application = _ready_application(db)
    intruder, _ = _ready_application(db)
    _script(_uses(_submit_call(application)))
    paused = client.post(
        CHAT_URL, headers=_headers(client, db, user), json={"message": "标记为已提交"}
    ).json()

    response = client.post(
        _runs_url(paused["run_id"], "approve"),
        headers=_headers(client, db, intruder),
    )

    assert response.status_code == 404
    db.refresh(application)
    assert application.status is ApplicationStatus.READY_TO_SUBMIT


# --------------------------------------------------------------------------
# C. 暂停 → 重启后端 → 批准
# --------------------------------------------------------------------------


def test_a_paused_run_survives_a_backend_restart(
    client: TestClient, db: Session
) -> None:
    user, application = _ready_application(db)
    headers = _headers(client, db, user)
    _script(_uses(_submit_call(application)), _answer("已经标记为已提交。"))

    paused = client.post(
        CHAT_URL, headers=headers, json={"message": "标记为已提交"}
    ).json()
    assert paused["status"] == "waiting_confirmation"

    # 内存里的一切都丢掉，只剩数据库里的 checkpoint
    _restart_backend()

    body = client.post(_runs_url(paused["run_id"], "approve"), headers=headers).json()

    assert body["status"] == "completed"
    assert body["answer"] == "已经标记为已提交。"
    db.refresh(application)
    assert application.status is ApplicationStatus.SUBMITTED


def test_a_confirmation_can_only_be_spent_once(client: TestClient, db: Session) -> None:
    user, application = _ready_application(db)
    headers = _headers(client, db, user)
    _script(_uses(_submit_call(application)), _answer("已经标记为已提交。"))

    paused = client.post(
        CHAT_URL, headers=headers, json={"message": "标记为已提交"}
    ).json()
    first = client.post(_runs_url(paused["run_id"], "approve"), headers=headers)
    second = client.post(_runs_url(paused["run_id"], "approve"), headers=headers)

    assert first.status_code == 200
    assert second.status_code == 404


def test_the_run_history_records_the_graph_engine(
    client: TestClient, db: Session
) -> None:
    """恢复要按运行自己的引擎路由，所以这一列必须写对。"""
    from app.modules.agent_runs.models import AgentRun

    user, _ = _ready_application(db)
    _script(_answer("好的。"))
    body = client.post(
        CHAT_URL, headers=_headers(client, db, user), json={"message": "你好"}
    ).json()

    run: Any = db.get(AgentRun, uuid.UUID(body["run_id"]))
    assert run is not None
    assert run.engine == "graph"
