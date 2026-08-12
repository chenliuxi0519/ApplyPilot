from app.harness.errors import HarnessError
from app.harness.models import (
    ToolCall,
    ToolContext,
    ToolResult,
    error_result,
    success_result,
    unexpected_result,
)


def execute_tool(*, call: ToolCall, ctx: ToolContext) -> ToolResult:
    try:
        output = call.definition.handler(ctx, call.payload)
    except HarnessError as error:
        return error_result(call_id=call.call_id, tool_name=call.tool_name, error=error)
    except Exception as error:
        return unexpected_result(
            call_id=call.call_id, tool_name=call.tool_name, error=error
        )
    return success_result(call_id=call.call_id, tool_name=call.tool_name, output=output)
