import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlmodel import Session

from app.agent.anthropic_client import AnthropicModelClient
from app.agent.budget import Budget
from app.agent.graph import AgentRuntimeContext, build_graph, new_state
from app.agent.recorder import InMemoryRunRecorder
from app.agent.state import AgentStatus
from app.core.config import settings
from app.harness import PolicyOutcome, ToolErrorCode
from app.tools import build_default_registry
from tests.utils.program import create_random_program, create_random_university
from tests.utils.user import create_random_user

pytestmark = pytest.mark.skipif(
    not settings.agent_is_configured,
    reason="AGENT_BASE_URL, AGENT_API_KEY and AGENT_MODEL are not all configured",
)


def test_the_agent_picks_the_search_tool_on_its_own(db: Session) -> None:
    university = create_random_university(db)
    create_random_program(db, university=university)
    user = create_random_user(db)

    model = AnthropicModelClient()
    run_id = uuid.uuid4()
    result = build_graph(InMemorySaver()).invoke(
        new_state(
            run_id,
            f"What programs does {university.short_name} offer?",
            model,
        ),
        config={"configurable": {"thread_id": f"smoke:{run_id}"}},
        context=AgentRuntimeContext(
            user_id=user.id,
            is_superuser=False,
            model=model,
            registry=build_default_registry(),
            recorder=InMemoryRunRecorder(),
            budget=Budget(max_steps=4, max_tool_calls=4),
            session=db,
        ),
    )
    model_events = [
        event for event in result["trace"] if event["event_type"] == "model_request"
    ]
    tool_events = [
        event for event in result["trace"] if event["event_type"] == "tool_call"
    ]

    print(f"\nendpoint:    {settings.AGENT_BASE_URL}")
    print(f"model:       {settings.AGENT_MODEL}")
    print(f"stop reasons:{[event['stop_reason'] for event in model_events]}")
    print(
        "tool calls:  "
        f"{[(event['tool_name'], event['tool_call_id']) for event in tool_events]}"
    )
    print(f"results:     {[event['tool_result_status'] for event in tool_events]}")
    print(f"steps: {result['step_count']}  tool calls: {result['tool_call_count']}")
    print(f"final answer: {result['final_answer']!r}")

    assert tool_events, "the endpoint returned no tool call"
    assert "search_programs" in {event["tool_name"] for event in tool_events}
    assert all(event["tool_call_id"] for event in tool_events)
    assert ToolErrorCode.INVALID_INPUT.value not in {
        event["error_code"] for event in tool_events
    }
    assert ToolErrorCode.UNKNOWN_TOOL.value not in {
        event["error_code"] for event in tool_events
    }
    assert PolicyOutcome.ALLOW.value in {
        event["policy_outcome"] for event in tool_events
    }
    assert "ok" in {event["tool_result_status"] for event in tool_events}
    assert len(model_events) >= 2, "the model never got a turn after the tool result"
    assert result["status"] == AgentStatus.COMPLETED.value
    assert result["final_answer"]
