"""在工具执行前校验名称和参数，不处理业务规则。"""

from typing import Any

from pydantic import ValidationError

from app.harness.errors import InvalidToolInputError, UnknownToolError
from app.harness.models import ToolCall
from app.harness.registry import ToolRegistry

RESERVED_ARGUMENT_NAMES = frozenset({"user_id", "is_superuser", "approved_call_ids"})


def validate_tool_call(
    *,
    registry: ToolRegistry,
    tool_name: str,
    raw_arguments: dict[str, Any],
    call_id: str,
) -> ToolCall:
    reserved = RESERVED_ARGUMENT_NAMES.intersection(raw_arguments)
    if reserved:
        # 用户身份只能来自登录上下文，模型不能通过参数自行指定。
        raise InvalidToolInputError(
            "工具参数不能包含用户身份或权限",
            {"reserved_arguments": sorted(reserved)},
        )

    definition = registry.try_get(tool_name)
    if definition is None:
        raise UnknownToolError(
            f"未知工具：{tool_name!r}",
            {"available_tools": registry.names()},
        )

    try:
        payload = definition.input_model.model_validate(raw_arguments)
    except ValidationError as error:
        raise InvalidToolInputError(
            f"工具 {tool_name!r} 的参数不符合要求",
            {"errors": error.errors(include_url=False, include_context=False)},
        ) from error

    return ToolCall(
        call_id=call_id,
        tool_name=tool_name,
        raw_arguments=raw_arguments,
        payload=payload,
        definition=definition,
    )
