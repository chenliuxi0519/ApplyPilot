import uuid

from sqlmodel import Session

from app.agent import AgentLoop, AgentState, AgentStatus, Budget
from app.core.db import engine
from app.harness import ExecutionContext, PermissionLevel, ToolRegistry
from tests.agent.conftest import FakeModelClient, call, text_response, tool_response
from tests.harness.conftest import make_definition


def _echo_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        make_definition(name="echo", permission_level=PermissionLevel.READ)
    )
    return registry


def _loop(script, budget: Budget) -> tuple[AgentLoop, FakeModelClient]:
    model = FakeModelClient(script)
    loop = AgentLoop(
        model=model,
        registry=_echo_registry(),
        session=Session(engine),
        execution=ExecutionContext(user_id=uuid.uuid4()),
        budget=budget,
    )
    return loop, model


def test_max_steps_stops_the_run() -> None:

    script = [
        tool_response(call("echo", {"message": "hi"}, call_id=f"c{i}"))
        for i in range(10)
    ]
    loop, model = _loop(script, Budget(max_steps=3, max_tool_calls=100))
    state = loop.run(AgentState.new(user_id=uuid.uuid4()), "go")

    assert state.status is AgentStatus.BUDGET_EXCEEDED
    assert state.step_count == 3
    assert model.calls == 3


def test_max_tool_calls_stops_the_run() -> None:
    script = [
        tool_response(call("echo", {"message": "hi"}, call_id=f"c{i}"))
        for i in range(10)
    ]
    loop, _ = _loop(script, Budget(max_steps=100, max_tool_calls=2))
    state = loop.run(AgentState.new(user_id=uuid.uuid4()), "go")

    assert state.status is AgentStatus.BUDGET_EXCEEDED
    assert state.tool_call_count == 2


def test_a_batch_that_would_overrun_is_not_started() -> None:
    script = [
        tool_response(
            call("echo", {"message": "a"}, call_id="c1"),
            call("echo", {"message": "b"}, call_id="c2"),
            call("echo", {"message": "c"}, call_id="c3"),
        )
    ]
    loop, _ = _loop(script, Budget(max_steps=10, max_tool_calls=2))
    state = loop.run(AgentState.new(user_id=uuid.uuid4()), "go")

    assert state.status is AgentStatus.BUDGET_EXCEEDED
    assert state.tool_call_count == 0


def test_a_run_within_budget_completes() -> None:
    script = [
        tool_response(call("echo", {"message": "hi"})),
        text_response("done"),
    ]
    loop, _ = _loop(script, Budget(max_steps=8, max_tool_calls=10))
    state = loop.run(AgentState.new(user_id=uuid.uuid4()), "go")

    assert state.status is AgentStatus.COMPLETED
    assert state.final_answer == "done"


def test_default_budget_values() -> None:
    budget = Budget()
    assert budget.max_steps == 8
    assert budget.max_tool_calls == 10
