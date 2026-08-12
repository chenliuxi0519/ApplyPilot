import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.agent.state import AgentState, AgentStatus
from app.agent.trace import TraceEvent, TraceEventType
from app.core.config import settings
from app.core.db import engine
from app.models import User
from app.modules.agent_runs.recorder import PostgresRunRecorder
from tests.utils.user import authentication_token_from_email, create_random_user

RUNS_URL = f"{settings.API_V1_STR}/agent/runs/"


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
