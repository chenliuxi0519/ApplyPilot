import pytest

from app.harness import (
    InvalidToolInputError,
    ToolErrorCode,
    ToolRegistry,
    UnknownToolError,
    validate_tool_call,
)
from tests.harness.conftest import EchoInput, exploding_handler, make_definition


def test_valid_arguments_produce_a_normalized_call(registry: ToolRegistry) -> None:
    call = validate_tool_call(
        registry=registry,
        tool_name="echo",
        raw_arguments={"message": "hi", "count": 2},
        call_id="call-1",
    )

    assert call.call_id == "call-1"
    assert call.tool_name == "echo"
    assert isinstance(call.payload, EchoInput)
    assert call.payload.count == 2

    assert call.raw_arguments == {"message": "hi", "count": 2}


def test_defaults_are_applied_during_normalization(registry: ToolRegistry) -> None:
    call = validate_tool_call(
        registry=registry,
        tool_name="echo",
        raw_arguments={"message": "hi"},
        call_id="call-1",
    )
    assert isinstance(call.payload, EchoInput)
    assert call.payload.count == 1


def test_unknown_tool_is_refused(registry: ToolRegistry) -> None:
    with pytest.raises(UnknownToolError) as error:
        validate_tool_call(
            registry=registry,
            tool_name="ghost",
            raw_arguments={},
            call_id="call-1",
        )
    assert error.value.code is ToolErrorCode.UNKNOWN_TOOL
    assert error.value.details is not None
    assert error.value.details["available_tools"] == ["echo"]


def test_missing_required_argument_is_refused(registry: ToolRegistry) -> None:
    with pytest.raises(InvalidToolInputError) as error:
        validate_tool_call(
            registry=registry,
            tool_name="echo",
            raw_arguments={},
            call_id="call-1",
        )
    assert error.value.code is ToolErrorCode.INVALID_INPUT
    assert error.value.details is not None
    assert error.value.details["errors"]


def test_wrong_argument_type_is_refused(registry: ToolRegistry) -> None:
    with pytest.raises(InvalidToolInputError):
        validate_tool_call(
            registry=registry,
            tool_name="echo",
            raw_arguments={"message": "hi", "count": "many"},
            call_id="call-1",
        )


def test_identity_cannot_be_supplied_as_an_argument(
    registry: ToolRegistry,
) -> None:
    with pytest.raises(InvalidToolInputError) as error:
        validate_tool_call(
            registry=registry,
            tool_name="echo",
            raw_arguments={"message": "hi", "user_id": "someone-else"},
            call_id="call-1",
        )
    assert error.value.details is not None
    assert error.value.details["reserved_arguments"] == ["user_id"]


def test_reserved_names_are_checked_before_the_tool_exists(
    registry: ToolRegistry,
) -> None:

    with pytest.raises(InvalidToolInputError):
        validate_tool_call(
            registry=registry,
            tool_name="ghost",
            raw_arguments={"is_superuser": True},
            call_id="call-1",
        )


def test_guard_never_executes_the_handler() -> None:
    registry = ToolRegistry()
    registry.register(make_definition(handler=exploding_handler))

    call = validate_tool_call(
        registry=registry,
        tool_name="echo",
        raw_arguments={"message": "hi"},
        call_id="call-1",
    )
    assert call.definition.handler is exploding_handler
