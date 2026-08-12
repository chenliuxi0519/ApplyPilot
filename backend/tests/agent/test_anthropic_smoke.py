import pytest
from sqlmodel import Session

from app.agent import AgentLoop, AgentState, AgentStatus, Budget
from app.agent.anthropic_client import AnthropicModelClient
from app.agent.trace import TraceEventType
from app.core.config import settings
from app.harness import ExecutionContext, PolicyOutcome, ToolErrorCode, ToolRegistry
from tests.utils.program import create_random_program, create_random_university
from tests.utils.user import create_random_user

pytestmark = pytest.mark.skipif(
    not settings.agent_is_configured,
    reason="AGENT_BASE_URL, AGENT_API_KEY and AGENT_MODEL are not all configured",
)


def test_the_agent_picks_the_search_tool_on_its_own(
    db: Session, registry: ToolRegistry
) -> None:
    university = create_random_university(db)
    create_random_program(db, university=university)
    user = create_random_user(db)

    loop = AgentLoop(
        model=AnthropicModelClient(),
        registry=registry,
        session=db,
        execution=ExecutionContext(user_id=user.id),
        budget=Budget(max_steps=4, max_tool_calls=4),
    )
    state = loop.run(
        AgentState.new(user_id=user.id),
        f"What programs does {university.short_name} offer?",
    )

    model_events = [
        event
        for event in state.trace
        if event.event_type is TraceEventType.MODEL_REQUEST
    ]
    tool_events = [
        event for event in state.trace if event.event_type is TraceEventType.TOOL_CALL
    ]

    print(f"\nendpoint:    {settings.AGENT_BASE_URL}")
    print(f"model:       {settings.AGENT_MODEL}")
    print(f"stop reasons:{[event.stop_reason for event in model_events]}")
    print(f"tool calls:  {[(e.tool_name, e.tool_call_id) for e in tool_events]}")
    print(f"results:     {[e.tool_result_status for e in tool_events]}")
    print(f"steps: {state.step_count}  tool calls: {state.tool_call_count}")
    print(f"final answer: {state.final_answer!r}")

    assert tool_events, "the endpoint returned no tool call"
    assert "search_programs" in {event.tool_name for event in tool_events}

    assert all(event.tool_call_id for event in tool_events)

    assert ToolErrorCode.INVALID_INPUT not in {
        event.error_code for event in tool_events
    }
    assert ToolErrorCode.UNKNOWN_TOOL not in {event.error_code for event in tool_events}

    assert PolicyOutcome.ALLOW in {event.policy_outcome for event in tool_events}

    assert "ok" in {event.tool_result_status for event in tool_events}

    assert len(model_events) >= 2, "the model never got a turn after the tool result"
    assert state.status is AgentStatus.COMPLETED
    assert state.final_answer
