from typing import Any

import pytest
from sqlmodel import Session

from app.harness import (
    ExecutionContext,
    ToolContext,
    ToolRegistry,
    validate_tool_call,
)
from app.models import User
from app.tools import build_default_registry


@pytest.fixture
def registry() -> ToolRegistry:
    return build_default_registry()


def make_context(db: Session, user: User) -> ToolContext:
    return ToolContext(
        session=db,
        execution=ExecutionContext(user_id=user.id, is_superuser=user.is_superuser),
    )


def run_tool(
    *,
    registry: ToolRegistry,
    ctx: ToolContext,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    call_id: str = "call-1",
) -> Any:
    call = validate_tool_call(
        registry=registry,
        tool_name=tool_name,
        raw_arguments=arguments or {},
        call_id=call_id,
    )
    return call.definition.handler(ctx, call.payload)
