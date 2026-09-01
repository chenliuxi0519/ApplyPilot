from app.harness.errors import HarnessError, ToolErrorCode, ToolExecutionError
from app.harness.idempotency import claim, complete, release
from app.harness.models import (
    PermissionLevel,
    ToolCall,
    ToolContext,
    ToolResult,
    error_result,
    success_result,
    unexpected_result,
)


def _invoke(*, call: ToolCall, ctx: ToolContext) -> ToolResult:
    try:
        output = call.definition.handler(ctx, call.payload)
    except HarnessError as error:
        return error_result(call_id=call.call_id, tool_name=call.tool_name, error=error)
    except Exception as error:
        return unexpected_result(
            call_id=call.call_id, tool_name=call.tool_name, error=error
        )
    return success_result(call_id=call.call_id, tool_name=call.tool_name, output=output)


def execute_tool(
    *, call: ToolCall, ctx: ToolContext, idempotency_key: str | None = None
) -> ToolResult:
    """执行一次工具调用。

    传了 idempotency_key 的写工具会被重放保护包住：同一个键第二次进来不会
    真的再执行一遍。只读工具不需要保护，重放它没有副作用。
    """
    # 用 effective_permission 而不是声明值：escalate 只会把等级往上抬，
    # 抬过的调用就不再算只读。
    read_only = call.definition.effective_permission(call.payload) is (
        PermissionLevel.READ
    )
    if idempotency_key is None or read_only:
        return _invoke(call=call, ctx=ctx)

    outcome = claim(
        session=ctx.session,
        user_id=ctx.user_id,
        key=idempotency_key,
        tool_name=call.tool_name,
    )

    if outcome.kind == "replay":
        # 上一次已经成功写过库了，这里只把当时的输出还原给模型。
        return success_result(
            call_id=call.call_id,
            tool_name=call.tool_name,
            output=call.definition.output_model.model_validate(outcome.output or {}),
        )

    if outcome.kind == "ambiguous":
        return error_result(
            call_id=call.call_id,
            tool_name=call.tool_name,
            error=ToolExecutionError(
                ToolErrorCode.CONFLICT,
                f"工具 {call.tool_name} 上一次执行中断，是否已经生效无法确定。"
                "请先向用户核对当前数据，不要直接重试。",
            ),
        )

    result = _invoke(call=call, ctx=ctx)
    if result.status == "ok":
        complete(
            session=ctx.session,
            key=idempotency_key,
            output=None
            if result.output is None
            else result.output.model_dump(mode="json"),
        )
    else:
        release(session=ctx.session, key=idempotency_key)
    return result
