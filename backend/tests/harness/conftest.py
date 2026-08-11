import uuid
from typing import Any

import pytest
from pydantic import BaseModel
from sqlmodel import SQLModel

from app.harness import (
    ExecutionContext,
    PermissionLevel,
    ToolCall,
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    validate_tool_call,
)


class EchoInput(SQLModel):
    message: str
    count: int = 1


class EchoOutput(SQLModel):
    echoed: str


def echo_handler(ctx: ToolContext, payload: Any) -> BaseModel:
    del ctx
    return EchoOutput(echoed=payload.message * payload.count)


def exploding_handler(ctx: ToolContext, payload: Any) -> BaseModel:
    del ctx, payload
    raise AssertionError("The guard and the policy must never run a handler")


def make_definition(
    *,
    name: str = "echo",
    permission_level: PermissionLevel = PermissionLevel.READ,
    handler: Any = echo_handler,
    escalate: Any = None,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Test tool {name}",
        input_model=EchoInput,
        output_model=EchoOutput,
        permission_level=permission_level,
        handler=handler,
        escalate=escalate,
    )


@pytest.fixture
def registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(make_definition())
    return registry


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext(user_id=uuid.uuid4())


def make_call(
    definition: ToolDefinition,
    *,
    call_id: str = "call-1",
    arguments: dict[str, Any] | None = None,
) -> ToolCall:
    registry = ToolRegistry()
    registry.register(definition)
    return validate_tool_call(
        registry=registry,
        tool_name=definition.name,
        raw_arguments=arguments or {"message": "hi"},
        call_id=call_id,
    )
