import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.agent.state import AgentState, AgentStatus
from app.agent.trace import TraceEvent, TraceEventType
from app.core.config import settings
from app.core.db import engine
from app.models import User
from app.modules.agent_runs import router as agent_runs_router
from app.modules.agent_runs import service as agent_run_service
from app.modules.agent_runs.models import AgentRun
from app.modules.agent_runs.recorder import PostgresRunRecorder
from tests.utils.user import authentication_token_from_email, create_random_user

RUNS_URL = f"{settings.API_V1_STR}/agent/runs/"


class _RecordingSaver:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


@pytest.fixture(autouse=True)
def checkpoint_saver(monkeypatch: pytest.MonkeyPatch) -> _RecordingSaver:
    saver = _RecordingSaver()
    monkeypatch.setattr(agent_runs_router, "get_checkpointer", lambda: saver)
    return saver


def _recorded_run(user: User, *, status=AgentStatus.COMPLETED) -> uuid.UUID:
    state = AgentState.new(user_id=user.id)
    recorder = PostgresRunRecorder(engine)
    recorder.start_run(state)
    recorder.record_event(
        state.run_id,
        0,
        TraceEvent(
            step=1,
            event_type=TraceEventType.MODEL_REQUEST,
            latency_ms=10,
            produced_tool_calls=1,
        ),
    )
    recorder.record_event(
        state.run_id,
        1,
        TraceEvent(
            step=1,
            event_type=TraceEventType.TOOL_CALL,
            latency_ms=25,
            tool_name="search_programs",
            tool_call_id="toolu_1",
            tool_result_status="ok",
        ),
    )
    state.status = status
    state.step_count = 2
    state.tool_call_count = 1
    state.final_answer = "Here you go."
    recorder.finish_run(state)
    return state.run_id


def _headers(client: TestClient, db: Session, user: User) -> dict[str, str]:
    return authentication_token_from_email(client=client, email=user.email, db=db)


def _set_conversation(db: Session, run_id: uuid.UUID, conversation_id: str) -> None:
    run = db.get(AgentRun, run_id)
    assert run is not None
    run.conversation_id = conversation_id
    db.add(run)
    db.commit()


def test_listing_requires_authentication(client: TestClient) -> None:
    assert client.get(RUNS_URL).status_code == 401


def test_a_user_sees_their_own_runs(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    me = client.get(
        f"{settings.API_V1_STR}/users/me", headers=normal_user_token_headers
    ).json()
    user = db.get(User, uuid.UUID(me["id"]))
    assert user is not None
    run_id = _recorded_run(user)

    response = client.get(RUNS_URL, headers=normal_user_token_headers)
    assert response.status_code == 200
    assert str(run_id) in {row["id"] for row in response.json()["data"]}


def test_run_detail_carries_metrics(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    me = client.get(
        f"{settings.API_V1_STR}/users/me", headers=normal_user_token_headers
    ).json()
    user = db.get(User, uuid.UUID(me["id"]))
    assert user is not None
    run_id = _recorded_run(user)

    response = client.get(f"{RUNS_URL}{run_id}", headers=normal_user_token_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["final_answer"] == "Here you go."
    assert body["metrics"]["task_success"] is True
    assert body["metrics"]["total_tool_calls"] == 1
    assert body["metrics"]["total_tool_latency_ms"] == 25
    assert body["metrics"]["run_duration_ms"] is not None


def test_events_come_back_in_sequence(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    me = client.get(
        f"{settings.API_V1_STR}/users/me", headers=normal_user_token_headers
    ).json()
    user = db.get(User, uuid.UUID(me["id"]))
    assert user is not None
    run_id = _recorded_run(user)

    response = client.get(
        f"{RUNS_URL}{run_id}/events", headers=normal_user_token_headers
    )
    assert response.status_code == 200
    events = response.json()["data"]
    assert [event["sequence"] for event in events] == [0, 1]
    assert events[1]["tool_name"] == "search_programs"

    assert not {"arguments", "output", "content"} & set(events[1])


def test_another_users_run_is_not_found(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    stranger = create_random_user(db)
    run_id = _recorded_run(stranger)

    assert (
        client.get(f"{RUNS_URL}{run_id}", headers=normal_user_token_headers).status_code
        == 404
    )
    assert (
        client.get(
            f"{RUNS_URL}{run_id}/events", headers=normal_user_token_headers
        ).status_code
        == 404
    )


def test_a_superuser_gets_no_special_access(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    stranger = create_random_user(db)
    run_id = _recorded_run(stranger)

    assert (
        client.get(f"{RUNS_URL}{run_id}", headers=superuser_token_headers).status_code
        == 404
    )


def test_an_unknown_run_is_not_found(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{RUNS_URL}{uuid.uuid4()}", headers=normal_user_token_headers
    )
    assert response.status_code == 404


def test_runs_can_be_filtered_by_status(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    me = client.get(
        f"{settings.API_V1_STR}/users/me", headers=normal_user_token_headers
    ).json()
    user = db.get(User, uuid.UUID(me["id"]))
    assert user is not None
    _recorded_run(user, status=AgentStatus.FAILED)

    response = client.get(
        RUNS_URL, headers=normal_user_token_headers, params={"status": "failed"}
    )
    assert response.status_code == 200
    assert response.json()["count"] >= 1
    assert all(row["status"] == "failed" for row in response.json()["data"])


def test_a_waiting_run_can_only_be_claimed_once(db: Session) -> None:
    user = create_random_user(db)
    run_id = _recorded_run(user, status=AgentStatus.WAITING_CONFIRMATION)

    assert agent_run_service.claim_waiting_run(
        session=db, user_id=user.id, run_id=run_id
    )
    assert not agent_run_service.claim_waiting_run(
        session=db, user_id=user.id, run_id=run_id
    )

    agent_run_service.restore_waiting_run(session=db, user_id=user.id, run_id=run_id)
    assert agent_run_service.claim_waiting_run(
        session=db, user_id=user.id, run_id=run_id
    )


def test_deleting_a_conversation_removes_every_run_in_it(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
    checkpoint_saver: _RecordingSaver,
) -> None:
    me = client.get(
        f"{settings.API_V1_STR}/users/me", headers=normal_user_token_headers
    ).json()
    user = db.get(User, uuid.UUID(me["id"]))
    assert user is not None
    conversation_id = f"c-{uuid.uuid4().hex}"
    first_run = _recorded_run(user)
    second_run = _recorded_run(user)
    _set_conversation(db, first_run, conversation_id)
    _set_conversation(db, second_run, conversation_id)

    response = client.delete(
        f"{RUNS_URL}conversations/{conversation_id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    assert checkpoint_saver.deleted == [f"{user.id}:{conversation_id}"]
    assert (
        client.get(
            f"{RUNS_URL}{first_run}", headers=normal_user_token_headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"{RUNS_URL}{second_run}", headers=normal_user_token_headers
        ).status_code
        == 404
    )
    # 事件表 ON DELETE CASCADE，随运行一起消失，不会留下孤儿行。
    remaining = db.get(AgentRun, first_run)
    assert remaining is None


def test_deleting_an_unknown_conversation_is_404(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    response = client.delete(
        f"{RUNS_URL}conversations/does-not-exist",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404


def test_a_user_cannot_delete_another_users_conversation(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    stranger = create_random_user(db)
    conversation_id = f"c-{uuid.uuid4().hex}"
    stranger_run = _recorded_run(stranger)
    _set_conversation(db, stranger_run, conversation_id)

    response = client.delete(
        f"{RUNS_URL}conversations/{conversation_id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    # 攻击者的请求没有删掉任何东西，受害者的运行记录原封不动。
    assert db.get(AgentRun, stranger_run) is not None
