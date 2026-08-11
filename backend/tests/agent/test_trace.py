import json
import uuid

from sqlmodel import Session

from app.agent import AgentLoop, AgentState, AgentStatus, TraceEventType
from app.agent.model import ModelStopReason
from app.core.db import engine
from app.harness import ExecutionContext, PermissionLevel, PolicyOutcome, ToolRegistry
from tests.agent.conftest import FakeModelClient, call, text_response, tool_response
from tests.harness.conftest import make_definition

SECRET = "chain-of-thought-marker-do-not-persist"


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        make_definition(name="echo", permission_level=PermissionLevel.READ)
    )
    return registry


def _run(script) -> AgentState:
    loop = AgentLoop(
        model=FakeModelClient(script),
        registry=_registry(),
        session=Session(engine),
        execution=ExecutionContext(user_id=uuid.uuid4()),
    )
    return loop.run(AgentState.new(user_id=uuid.uuid4()), "go")


def test_event_sequence_for_a_tool_run() -> None:
    state = _run(
        [
            tool_response(call("echo", {"message": "hi"}, call_id="call-9")),
            text_response("done"),
        ]
    )

    assert [event.event_type for event in state.trace] == [
        TraceEventType.MODEL_REQUEST,
        TraceEventType.TOOL_CALL,
        TraceEventType.MODEL_REQUEST,
        TraceEventType.RUN_FINISHED,
    ]


def test_model_events_carry_stop_reason_and_call_count() -> None:
    state = _run(
        [tool_response(call("echo", {"message": "hi"})), text_response("done")]
    )
    model_events = [
        e for e in state.trace if e.event_type is TraceEventType.MODEL_REQUEST
    ]

    assert model_events[0].stop_reason is ModelStopReason.TOOL_USE
    assert model_events[0].produced_tool_calls == 1
    assert model_events[1].stop_reason is ModelStopReason.END_TURN
    assert model_events[1].produced_tool_calls == 0
    assert all(event.latency_ms >= 0 for event in model_events)


def test_tool_events_carry_identity_policy_and_result() -> None:
    state = _run(
        [
            tool_response(call("echo", {"message": "hi"}, call_id="call-9")),
            text_response("done"),
        ]
    )
    tool_event = next(
        e for e in state.trace if e.event_type is TraceEventType.TOOL_CALL
    )

    assert tool_event.tool_name == "echo"
    assert tool_event.tool_call_id == "call-9"
    assert tool_event.policy_outcome is PolicyOutcome.ALLOW
    assert tool_event.tool_result_status == "ok"
    assert tool_event.error_code is None


def test_error_events_carry_the_error_code() -> None:
    state = _run([tool_response(call("ghost", {})), text_response("no such tool")])
    tool_event = next(
        e for e in state.trace if e.event_type is TraceEventType.TOOL_CALL
    )

    assert tool_event.tool_result_status == "error"
    assert tool_event.error_code is not None


def test_final_event_records_the_status() -> None:
    state = _run([text_response("done")])
    final = state.trace[-1]

    assert final.event_type is TraceEventType.RUN_FINISHED
    assert final.final_status == AgentStatus.COMPLETED.value


def test_trace_never_carries_model_text_or_tool_payloads() -> None:
    state = _run(
        [
            tool_response(call("echo", {"message": SECRET}, call_id="call-9")),
            text_response(SECRET),
        ]
    )

    serialized = json.dumps(state.trace_dicts())

    assert SECRET not in serialized
    assert "message" not in serialized

    assert "call-9" in serialized
    assert "echo" in serialized
