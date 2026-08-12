from collections.abc import Sequence
from typing import Any

import pytest
from sqlmodel import Session

from app.agent.model import ModelResponse, ModelStopReason, ModelToolCall
from app.harness import ExecutionContext, ToolRegistry, ToolResult
from app.models import User
from app.tools import build_default_registry


class FakeModelClient:
    def __init__(self, script: Sequence[ModelResponse]) -> None:
        self._script = list(script)
        self.calls = 0
        self.seen_tools: list[list[dict[str, Any]]] = []
        self.seen_messages: list[list[Any]] = []
        self.seen_system: list[str] = []

    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Any],
        tools: Sequence[dict[str, Any]],
    ) -> ModelResponse:
        self.seen_system.append(system)
        self.seen_tools.append(list(tools))
        self.seen_messages.append(list(messages))
        if self.calls >= len(self._script):
            raise AssertionError(
                f"The loop asked for step {self.calls + 1} but the script has "
                f"{len(self._script)} responses"
            )
        response = self._script[self.calls]
        self.calls += 1
        return response

    def user_message(self, text: str) -> Any:
        return {"role": "user", "content": text}

    def tool_result_message(self, results: Sequence[ToolResult]) -> Any:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": result.call_id,
                    "is_error": result.status == "error",
                    "result": result.to_dict(),
                }
                for result in results
            ],
        }


def text_response(text: str) -> ModelResponse:
    return ModelResponse(
        stop_reason=ModelStopReason.END_TURN,
        text=text,
        tool_calls=(),
        assistant_message={"role": "assistant", "content": text},
    )


def tool_response(*calls: ModelToolCall) -> ModelResponse:
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


def refusal_response() -> ModelResponse:
    return ModelResponse(
        stop_reason=ModelStopReason.REFUSAL,
        text=None,
        tool_calls=(),
        assistant_message={"role": "assistant", "content": []},
    )


def call(
    name: str, arguments: dict[str, Any], call_id: str = "call-1"
) -> ModelToolCall:
    return ModelToolCall(id=call_id, name=name, arguments=arguments)


def context_for(user: User) -> ExecutionContext:
    return ExecutionContext(user_id=user.id, is_superuser=user.is_superuser)


@pytest.fixture
def registry() -> ToolRegistry:
    return build_default_registry()


def make_loop(
    *,
    db: Session,
    user: User,
    script: Sequence[ModelResponse],
    registry: ToolRegistry,
    budget: Any = None,
    approved_call_ids: frozenset[str] = frozenset(),
    recorder: Any = None,
) -> tuple[Any, FakeModelClient]:
    from app.agent import AgentLoop

    model = FakeModelClient(script)
    loop = AgentLoop(
        model=model,
        registry=registry,
        session=db,
        execution=ExecutionContext(
            user_id=user.id,
            is_superuser=user.is_superuser,
            approved_call_ids=approved_call_ids,
        ),
        budget=budget,
        recorder=recorder,
    )
    return loop, model
