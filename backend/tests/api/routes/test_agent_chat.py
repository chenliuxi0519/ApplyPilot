import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.agent.model import ModelResponse, ModelStopReason, ModelToolCall
from app.agent.session_store import AgentSessionStore
from app.api.routes import agent_chat
from app.core.config import settings
from app.main import app
from app.models import User
from app.modules.applications.models import Application, ApplicationStatus
from tests.utils.application import create_application_for
from tests.utils.program import create_random_program
from tests.utils.user import authentication_token_from_email

CHAT_URL = f"{settings.API_V1_STR}/agent/chat"


def _runs_url(run_id: uuid.UUID, action: str) -> str:
    return f"{settings.API_V1_STR}/agent/runs/{run_id}/{action}"


class _ScriptedModel:
    def __init__(self, script: list[ModelResponse]) -> None:
        self._script = script
        self.calls = 0

    def complete(self, **kwargs: Any) -> ModelResponse:
        del kwargs
        if self.calls >= len(self._script):
            raise AssertionError("the loop asked for more steps than scripted")
        response = self._script[self.calls]
        self.calls += 1
        return response

    def user_message(self, text: str) -> Any:
        return {"role": "user", "content": text}

    def tool_result_message(self, results: Any) -> Any:
        return {"role": "user", "content": "results"}


def _answer(text: str) -> ModelResponse:
    return ModelResponse(
        stop_reason=ModelStopReason.END_TURN,
        text=text,
        tool_calls=(),
        assistant_message={"role": "assistant", "content": text},
    )


def _calls(*tool_calls: ModelToolCall) -> ModelResponse:
    return ModelResponse(
        stop_reason=ModelStopReason.TOOL_USE,
        text=None,
        tool_calls=tool_calls,
        assistant_message={"role": "assistant", "content": "tool use"},
    )


def _call(
    name: str, arguments: dict[str, Any], call_id: str = "toolu_1"
) -> ModelToolCall:
    return ModelToolCall(id=call_id, name=name, arguments=arguments)


@pytest.fixture(autouse=True)
def store() -> Generator[AgentSessionStore]:
    fresh = AgentSessionStore()
    app.dependency_overrides[agent_chat.get_session_store] = lambda: fresh
    yield fresh
    app.dependency_overrides.pop(agent_chat.get_session_store, None)


def _script(*responses: ModelResponse) -> _ScriptedModel:
    model = _ScriptedModel(list(responses))
    app.dependency_overrides[agent_chat.get_model_client] = lambda: model
    return model


@pytest.fixture(autouse=True)
def _clear_model_override() -> Generator[None]:
    yield
    app.dependency_overrides.pop(agent_chat.get_model_client, None)


def _headers(client: TestClient, db: Session, user: User) -> dict[str, str]:
    return authentication_token_from_email(client=client, email=user.email, db=db)


def _me(client: TestClient, headers: dict[str, str], db: Session) -> User:
    body = client.get(f"{settings.API_V1_STR}/users/me", headers=headers).json()
    user = db.get(User, uuid.UUID(body["id"]))
    assert user is not None
    return user


def test_chat_requires_authentication(client: TestClient) -> None:
    assert client.post(CHAT_URL, json={"message": "hi"}).status_code == 401


def test_an_empty_message_is_refused(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    _script(_answer("hello"))
    response = client.post(
        CHAT_URL, headers=normal_user_token_headers, json={"message": "   "}
    )
    assert response.status_code == 422


def test_a_plain_answer_comes_back_with_a_run_id(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    _script(_answer("Here is what I found."))
    body = client.post(
        CHAT_URL, headers=normal_user_token_headers, json={"message": "hello"}
    ).json()

    assert body["status"] == "completed"
    assert body["answer"] == "Here is what I found."
    assert body["confirmation"] is None
    assert uuid.UUID(body["run_id"])
    assert body["conversation_id"].startswith("c-")


def test_a_completed_turn_can_be_restored_from_run_history(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    _script(_answer("这是持久化的回答。"))
    turn = client.post(
        CHAT_URL,
        headers=normal_user_token_headers,
        json={"message": "请记住这个问题"},
    ).json()

    history = client.get(
        f"{settings.API_V1_STR}/agent/runs/",
        headers=normal_user_token_headers,
    ).json()["data"]
    saved = next(row for row in history if row["id"] == turn["run_id"])
    assert saved["conversation_id"] == turn["conversation_id"]
    assert saved["user_message"] == "请记住这个问题"
    assert saved["response_payload"]["answer"] == "这是持久化的回答。"


def test_a_search_produces_a_program_ui_event(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
) -> None:
    program = create_random_program(db)
    _script(
        _calls(_call("search_programs", {"query": program.name})),
        _answer("Found one."),
    )
    body = client.post(
        CHAT_URL, headers=normal_user_token_headers, json={"message": "find programs"}
    ).json()

    events = [event for event in body["ui_events"] if event["type"] == "programs"]
    assert events, body["ui_events"]
    assert events[0]["data"]["count"] >= 1
    assert {"program_id", "name", "university", "region"} <= set(
        events[0]["data"]["programs"][0]
    )


def test_a_tool_without_a_projector_produces_no_card(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    _script(_calls(_call("get_user_profile", {})), _answer("No profile yet."))
    body = client.post(
        CHAT_URL, headers=normal_user_token_headers, json={"message": "my profile?"}
    ).json()

    assert body["ui_events"] == []
    assert body["tool_trace"] == [{"label": "已读取个人档案", "status": "error"}]


def test_the_response_never_carries_arguments_or_model_content(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
) -> None:
    program = create_random_program(db)
    _script(
        _calls(_call("search_programs", {"query": program.name})),
        _answer("Found one."),
    )
    body = client.post(
        CHAT_URL, headers=normal_user_token_headers, json={"message": "find programs"}
    ).json()

    assert not {"arguments", "messages", "system", "content", "trace"} & set(body)
    assert program.name not in str(body.get("tool_trace"))


def _pause_on_withdraw(
    client: TestClient, db: Session, headers: dict[str, str], user: User
) -> tuple[dict[str, Any], Application]:
    _, application, _ = create_application_for(db, user=user)
    _script(
        _calls(
            _call(
                "update_application_status",
                {
                    "application_id": str(application.id),
                    "target_status": "withdrawn",
                    "version": application.version,
                },
            )
        ),
        _answer("Done."),
    )
    body = client.post(
        CHAT_URL, headers=headers, json={"message": "withdraw it"}
    ).json()
    return body, application


def test_a_high_risk_write_pauses_and_changes_nothing(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
) -> None:
    user = _me(client, normal_user_token_headers, db)
    body, application = _pause_on_withdraw(client, db, normal_user_token_headers, user)

    assert body["status"] == "waiting_confirmation"
    assert body["answer"] is None
    confirmation = body["confirmation"]
    assert confirmation["tool_name"] == "update_application_status"
    assert confirmation["permission_level"] == "high_risk_write"
    assert confirmation["summary"]["target_status"] == "withdrawn"
    assert confirmation["summary"]["current_status"] == "shortlisted"
    assert confirmation["summary"]["program_label"]

    db.expire_all()
    assert db.get(Application, application.id).status is ApplicationStatus.SHORTLISTED


def test_approving_applies_the_change(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
) -> None:
    user = _me(client, normal_user_token_headers, db)
    body, application = _pause_on_withdraw(client, db, normal_user_token_headers, user)

    resumed = client.post(
        _runs_url(uuid.UUID(body["run_id"]), "approve"),
        headers=normal_user_token_headers,
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"

    db.expire_all()
    assert db.get(Application, application.id).status is ApplicationStatus.WITHDRAWN


def test_rejecting_leaves_the_application_alone(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
) -> None:
    user = _me(client, normal_user_token_headers, db)
    body, application = _pause_on_withdraw(client, db, normal_user_token_headers, user)

    resumed = client.post(
        _runs_url(uuid.UUID(body["run_id"]), "reject"),
        headers=normal_user_token_headers,
    )
    assert resumed.status_code == 200

    assert resumed.json()["status"] == "completed"

    db.expire_all()
    assert db.get(Application, application.id).status is ApplicationStatus.SHORTLISTED


def test_a_confirmation_can_only_be_spent_once(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
) -> None:
    user = _me(client, normal_user_token_headers, db)
    body, _ = _pause_on_withdraw(client, db, normal_user_token_headers, user)
    run_id = uuid.UUID(body["run_id"])

    assert (
        client.post(
            _runs_url(run_id, "approve"), headers=normal_user_token_headers
        ).status_code
        == 200
    )
    assert (
        client.post(
            _runs_url(run_id, "approve"), headers=normal_user_token_headers
        ).status_code
        == 404
    )


def test_another_user_cannot_approve_a_pending_run(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
) -> None:
    user = _me(client, normal_user_token_headers, db)
    body, application = _pause_on_withdraw(client, db, normal_user_token_headers, user)

    stranger = _stranger(client, db)
    response = client.post(
        _runs_url(uuid.UUID(body["run_id"]), "approve"), headers=stranger
    )

    assert response.status_code == 404
    db.expire_all()
    assert db.get(Application, application.id).status is ApplicationStatus.SHORTLISTED


def _stranger(client: TestClient, db: Session) -> dict[str, str]:
    from tests.utils.user import create_random_user

    other = create_random_user(db)
    return _headers(client, db, other)


def test_an_unknown_run_is_not_found(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    response = client.post(
        _runs_url(uuid.uuid4(), "approve"), headers=normal_user_token_headers
    )
    assert response.status_code == 404


def test_resume_requires_authentication(client: TestClient) -> None:
    assert client.post(_runs_url(uuid.uuid4(), "approve")).status_code == 401


def test_a_follow_up_carries_the_previous_transcript(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    model = _script(_answer("first"), _answer("second"))
    first = client.post(
        CHAT_URL, headers=normal_user_token_headers, json={"message": "one"}
    ).json()

    second = client.post(
        CHAT_URL,
        headers=normal_user_token_headers,
        json={"message": "two", "conversation_id": first["conversation_id"]},
    ).json()

    assert second["conversation_id"] == first["conversation_id"]
    assert second["run_id"] != first["run_id"]
    assert model.calls == 2


def test_another_users_conversation_id_starts_fresh(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
) -> None:
    _script(_answer("mine"), _answer("theirs"))
    mine = client.post(
        CHAT_URL, headers=normal_user_token_headers, json={"message": "one"}
    ).json()

    stranger = _stranger(client, db)
    theirs = client.post(
        CHAT_URL,
        headers=stranger,
        json={"message": "two", "conversation_id": mine["conversation_id"]},
    ).json()
    assert theirs["status"] == "completed"


def test_the_config_endpoint_reports_whether_the_agent_can_run(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/agent/config", headers=normal_user_token_headers
    )
    assert response.status_code == 200
    assert response.json()["configured"] == settings.agent_is_configured
