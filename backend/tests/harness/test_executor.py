import uuid

import pytest
from pydantic import BaseModel
from sqlmodel import Session

from app.core.db import engine
from app.harness import (
    ExecutionContext,
    PermissionLevel,
    ToolContext,
    ToolErrorCode,
    ToolExecutionError,
    ToolRegistry,
    execute_tool,
    validate_tool_call,
)
from tests.harness.conftest import EchoOutput, make_definition


def _ctx() -> ToolContext:

    return ToolContext(
        session=Session(engine), execution=ExecutionContext(user_id=uuid.uuid4())
    )


def _call(handler):
    registry = ToolRegistry()
    registry.register(
        make_definition(
            name="echo", permission_level=PermissionLevel.READ, handler=handler
        )
    )
    return validate_tool_call(
        registry=registry,
        tool_name="echo",
        raw_arguments={"message": "hi"},
        call_id="call-1",
    )


def test_successful_handler_returns_an_ok_result() -> None:
    result = execute_tool(call=_call(_ok_handler), ctx=_ctx())

    assert result.status == "ok"
    assert result.error is None
    assert isinstance(result.output, EchoOutput)
    assert result.call_id == "call-1"
    assert result.tool_name == "echo"


def test_classified_failure_keeps_its_error_code() -> None:
    result = execute_tool(call=_call(_not_found_handler), ctx=_ctx())

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code is ToolErrorCode.NOT_FOUND
    assert result.output is None


def test_unexpected_failure_becomes_an_internal_error_not_an_exception() -> None:
    result = execute_tool(call=_call(_exploding_handler), ctx=_ctx())

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INTERNAL
    assert "boom" in result.error.message


def test_result_serializes_for_the_model() -> None:
    payload = execute_tool(call=_call(_ok_handler), ctx=_ctx()).to_dict()
    assert payload["status"] == "ok"
    assert payload["output"] == {"echoed": "hi"}


def test_executor_does_not_revalidate_arguments() -> None:
    call = _call(_ok_handler)
    object.__setattr__(call, "raw_arguments", {"message": 12345})
    result = execute_tool(call=call, ctx=_ctx())

    assert result.status == "ok"


def _ok_handler(ctx: ToolContext, payload: object) -> BaseModel:
    del ctx
    return EchoOutput(echoed=payload.message)  # type: ignore[attr-defined]


def _not_found_handler(ctx: ToolContext, payload: object) -> BaseModel:
    del ctx, payload
    raise ToolExecutionError(ToolErrorCode.NOT_FOUND, "nothing here")


def _exploding_handler(ctx: ToolContext, payload: object) -> BaseModel:
    del ctx, payload
    raise RuntimeError("boom")


@pytest.mark.parametrize("handler", [_ok_handler, _not_found_handler])
def test_executor_never_raises(handler) -> None:
    execute_tool(call=_call(handler), ctx=_ctx())
