"""最小 LangGraph 编排。

只负责"什么时候调模型、什么时候执行工具、什么时候停下来等人确认"。
参数校验、权限判定、工具执行、领域规则全部沿用 app.harness 与既有工具，
节点里不复制任何业务逻辑。

身份不进 state：user_id / is_superuser 每次请求从 JWT 结果注入 Runtime
Context，checkpoint 里存的东西永远不能成为提权的入口。
"""

import logging
import operator
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from time import monotonic
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from sqlmodel import Session

from app.agent.budget import Budget
from app.agent.context import (
    SUMMARY_SYSTEM_PROMPT,
    ContextBudget,
    compose_system,
    estimate_tokens,
    plan_history,
)
from app.agent.evidence import extract as extract_evidence
from app.agent.evidence import render as render_evidence
from app.agent.model import ModelClient, ModelStopReason, ModelToolCall
from app.agent.prompt import SYSTEM_PROMPT
from app.agent.recorder import RunRecorder
from app.agent.state import AgentState, AgentStatus, PendingConfirmation
from app.agent.trace import TraceEvent, TraceEventType
from app.agent.verifier import (
    CITATION_INSTRUCTIONS,
    conservative_answer,
    correction_request,
    verify,
)
from app.harness import (
    ExecutionContext,
    HarnessError,
    PermissionDeniedError,
    PolicyOutcome,
    ToolContext,
    ToolError,
    ToolErrorCode,
    ToolRegistry,
    ToolResult,
    UserRejectedError,
    decide,
    error_result,
    execute_tool,
    validate_tool_call,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentRuntimeContext:
    """每次请求现场构造，绝不写进 checkpoint。"""

    user_id: uuid.UUID
    is_superuser: bool
    session: Session
    model: ModelClient
    registry: ToolRegistry
    recorder: RunRecorder
    budget: Budget
    # 读业务事实的回调。由 API 层注入，编排层因此不用认识领域模块。
    business_context: Callable[[], tuple[str, int]] = lambda: ("", 0)
    context_budget: ContextBudget = field(default_factory=ContextBudget)


class AgentGraphState(TypedDict):
    """字段与既有 AgentState 一一对应，去掉了身份，全部是纯 JSON。

    messages 和 trace 用累加 reducer，节点只返回新增的部分，
    这样中断和重放都不会把历史重复追加一遍。
    """

    messages: Annotated[list[dict[str, Any]], operator.add]
    trace: Annotated[list[dict[str, Any]], operator.add]
    run_id: str
    status: str
    final_answer: str | None
    last_error: dict[str, Any] | None
    pending_calls: list[dict[str, Any]]
    approval_call_ids: list[str]
    pending_confirmation: dict[str, Any] | None
    approved: bool
    step_count: int
    tool_call_count: int
    # 早前对话的摘要，以及它覆盖了 messages 前多少条。
    summary: str | None
    summarized_count: int
    # 本轮工具真正读到过的证据，引用只能来自这里。
    evidence: Annotated[list[dict[str, Any]], operator.add]


def new_state(run_id: uuid.UUID, message: str, model: ModelClient) -> AgentGraphState:
    return AgentGraphState(
        messages=[model.user_message(message)],
        trace=[],
        run_id=str(run_id),
        status=AgentStatus.RUNNING.value,
        final_answer=None,
        last_error=None,
        pending_calls=[],
        approval_call_ids=[],
        pending_confirmation=None,
        approved=False,
        step_count=0,
        tool_call_count=0,
        summary=None,
        summarized_count=0,
        evidence=[],
    )


# --------------------------------------------------------------------------
# 复用既有 recorder：它要的是 AgentState，这里现搭一个给它
# --------------------------------------------------------------------------


def _as_run_state(state: AgentGraphState, ctx: AgentRuntimeContext) -> AgentState:
    error = state["last_error"]
    return AgentState(
        run_id=uuid.UUID(state["run_id"]),
        user_id=ctx.user_id,
        status=AgentStatus(state["status"]),
        step_count=state["step_count"],
        tool_call_count=state["tool_call_count"],
        final_answer=state["final_answer"],
        last_error=None
        if error is None
        else ToolError(
            code=ToolErrorCode(error["code"]),
            message=error["message"],
            details=error.get("details"),
        ),
    )


def _record(
    state: AgentGraphState, ctx: AgentRuntimeContext, events: Sequence[TraceEvent]
) -> list[dict[str, Any]]:
    """写运行记录并返回要并进 state 的 trace 增量。

    sequence 取当前 trace 长度，和旧实现一致。记录失败不能打断业务，
    只记异常类型——数据库异常的 str() 会带上 SQL 参数。
    """
    base = len(state["trace"])
    run_id = uuid.UUID(state["run_id"])
    for offset, event in enumerate(events):
        try:
            ctx.recorder.record_event(run_id, base + offset, event)
        except Exception as error:  # noqa: BLE001 - 记录失败不能打断主流程
            logger.error(
                "run %s: could not record execution history: %s",
                state["run_id"],
                type(error).__name__,
            )
            logger.debug(
                "run %s: recorder failure detail", state["run_id"], exc_info=True
            )
    return [event.to_dict() for event in events]


def _summarize(
    ctx: AgentRuntimeContext, previous: str | None, older: list[Any]
) -> str | None:
    """把一段旧历史压成摘要。只在跨过阈值时调用一次，不是每轮都调。

    摘要失败不能让整轮对话失败：拿不到就沿用旧摘要。
    """
    if not older:
        return previous
    request = list(older)
    if previous:
        request = [
            ctx.model.user_message(f"这是更早对话的摘要，请一并合并：{previous}"),
            *request,
        ]
    request.append(ctx.model.user_message("请按系统提示总结以上对话。"))
    try:
        response = ctx.model.complete(
            system=SUMMARY_SYSTEM_PROMPT, messages=request, tools=[]
        )
    except Exception as error:  # noqa: BLE001 - 摘要失败不能打断对话
        logger.warning("could not summarize history: %s", type(error).__name__)
        return previous
    return response.text or previous


def _verified_answer(
    ctx: AgentRuntimeContext,
    state: AgentGraphState,
    system: str,
    sent: list[Any],
    response: Any,
) -> str:
    """核对最终回答的引用：通过就用它，不通过最多重写一次，再不行就保守回答。

    没有 Reviewer Agent、没有 reflection 循环——一次受控重试，边界写死。
    """
    records = state["evidence"]
    body, verdict = verify(response.text, records)
    if verdict.ok:
        return body

    retry_messages = [
        *sent,
        response.assistant_message,
        ctx.model.user_message(correction_request(verdict)),
    ]
    try:
        second = ctx.model.complete(system=system, messages=retry_messages, tools=[])
    except Exception as error:  # noqa: BLE001 - 重写失败就走保守回答
        logger.warning("could not regenerate answer: %s", type(error).__name__)
        return conservative_answer(verdict)

    retry_body, retry_verdict = verify(second.text, records)
    if retry_verdict.ok:
        return retry_body
    return conservative_answer(retry_verdict)


def _error(message: str) -> dict[str, Any]:
    return {"code": ToolErrorCode.INTERNAL.value, "message": message, "details": None}


# --------------------------------------------------------------------------
# 节点
# --------------------------------------------------------------------------


def call_model(
    state: AgentGraphState, runtime: Runtime[AgentRuntimeContext]
) -> dict[str, Any]:
    ctx = runtime.context
    if ctx.budget.steps_exhausted(state["step_count"]):
        return {"status": AgentStatus.BUDGET_EXCEEDED.value}

    step = state["step_count"] + 1

    # 历史太长就先压缩一次，再决定这轮送哪一段给模型。
    summarized_count, cut = plan_history(
        state["messages"], state["summarized_count"], ctx.context_budget
    )
    summary = state["summary"]
    did_summarize = summarized_count > state["summarized_count"]
    if did_summarize:
        summary = _summarize(
            ctx,
            summary,
            state["messages"][state["summarized_count"] : summarized_count],
        )

    business_context, profile_fields = ctx.business_context()
    evidence_block = render_evidence(state["evidence"])
    system = compose_system(
        SYSTEM_PROMPT + "\n\n" + CITATION_INSTRUCTIONS,
        business_context + ("\n\n" + evidence_block if evidence_block else ""),
        summary,
    )
    sent = state["messages"][cut:]

    started = monotonic()
    response = ctx.model.complete(
        system=system,
        messages=sent,
        tools=list(ctx.registry.llm_schemas()),
    )
    trace = _record(
        state,
        ctx,
        [
            TraceEvent(
                step=step,
                event_type=TraceEventType.MODEL_REQUEST,
                latency_ms=int((monotonic() - started) * 1000),
                stop_reason=response.stop_reason,
                produced_tool_calls=len(response.tool_calls),
                history_count=len(sent),
                estimated_tokens=estimate_tokens(system, sent),
                summarized=did_summarize,
                profile_fields=profile_fields,
            )
        ],
    )
    update: dict[str, Any] = {
        "messages": [response.assistant_message],
        "trace": trace,
        "step_count": step,
        "summary": summary,
        "summarized_count": summarized_count,
    }

    if response.stop_reason is ModelStopReason.REFUSAL:
        return {
            **update,
            "status": AgentStatus.FAILED.value,
            "last_error": _error("模型拒绝了本次请求"),
        }
    if response.stop_reason is ModelStopReason.MAX_TOKENS:
        return {
            **update,
            "status": AgentStatus.FAILED.value,
            "last_error": _error("模型回答达到输出长度上限"),
        }

    if not response.tool_calls:
        answer = _verified_answer(ctx, state, system, sent, response)
        return {
            **update,
            "status": AgentStatus.COMPLETED.value,
            "final_answer": answer,
        }

    if ctx.budget.would_exceed_tool_calls(
        state["tool_call_count"], len(response.tool_calls)
    ):
        return {**update, "status": AgentStatus.BUDGET_EXCEEDED.value}

    return {**update, "pending_calls": [call.to_dict() for call in response.tool_calls]}


def route_tools(
    state: AgentGraphState, runtime: Runtime[AgentRuntimeContext]
) -> dict[str, Any]:
    """校验参数、判权限，挑出需要用户确认的调用。

    校验和判权限都走 harness，这里不含任何业务判断；纯函数，重放安全。
    """
    ctx = runtime.context
    execution = ExecutionContext(user_id=ctx.user_id, is_superuser=ctx.is_superuser)

    needs_approval: list[str] = []
    confirmation: dict[str, Any] | None = None
    for raw in state["pending_calls"]:
        model_call = ModelToolCall.from_dict(raw)
        try:
            call = validate_tool_call(
                registry=ctx.registry,
                tool_name=model_call.name,
                raw_arguments=model_call.arguments,
                call_id=model_call.id,
            )
        except HarnessError:
            continue  # 参数不合法，交给 execute_tools 变成错误结果回给模型
        decision = decide(context=execution, call=call)
        if decision.outcome is PolicyOutcome.REQUIRE_HUMAN_CONFIRMATION:
            needs_approval.append(model_call.id)
            if confirmation is None:
                confirmation = PendingConfirmation(
                    call_id=call.call_id,
                    tool_name=call.tool_name,
                    permission_level=decision.permission_level,
                    reason=decision.reason,
                    arguments=dict(model_call.arguments),
                ).to_dict()

    if not needs_approval:
        return {"approval_call_ids": [], "pending_confirmation": None}

    # 记录"需要确认"并把运行标成等待中，必须在 interrupt 之前、且在一个
    # 正常返回的节点里完成：中断会丢弃当前节点的状态写入，恢复时该节点
    # 又会从头重跑。放在这里，恢复时不会重跑，事件也就不会写第二遍。
    events = [
        TraceEvent(
            step=state["step_count"],
            event_type=TraceEventType.HUMAN_CONFIRMATION_REQUIRED,
            latency_ms=0,
            tool_name=_name_of(state["pending_calls"], call_id),
            tool_call_id=call_id,
        )
        for call_id in sorted(needs_approval)
    ]
    waiting = {**state, "status": AgentStatus.WAITING_CONFIRMATION.value}
    trace = _record(state, ctx, events)
    try:
        ctx.recorder.finish_run(_as_run_state(waiting, ctx))  # type: ignore[arg-type]
    except Exception as error:  # noqa: BLE001 - 记录失败不能打断主流程
        logger.error(
            "run %s: could not mark the run as waiting: %s",
            state["run_id"],
            type(error).__name__,
        )
    return {
        "approval_call_ids": needs_approval,
        "pending_confirmation": confirmation,
        "trace": trace,
        "status": AgentStatus.WAITING_CONFIRMATION.value,
    }


def _name_of(pending_calls: Sequence[dict[str, Any]], call_id: str) -> str | None:
    return next((call["name"] for call in pending_calls if call["id"] == call_id), None)


def human_approval(
    state: AgentGraphState, runtime: Runtime[AgentRuntimeContext]
) -> dict[str, Any]:
    """停下来等用户确认。

    函数体只有 interrupt 和它的结果处理：恢复时节点会从头重跑，
    这里不做任何外部写入，重跑也就不会产生重复记录。
    """
    decision = interrupt(
        {
            "call_ids": state["approval_call_ids"],
            "confirmation": state["pending_confirmation"],
        }
    )
    approved = bool(decision.get("approved")) if isinstance(decision, dict) else False

    # 下面这些只在恢复之后才会执行：interrupt 之前不做任何外部写入。
    kind = TraceEventType.HUMAN_APPROVED if approved else TraceEventType.HUMAN_REJECTED
    events = [
        TraceEvent(
            step=state["step_count"],
            event_type=kind,
            latency_ms=0,
            tool_name=_name_of(state["pending_calls"], call_id),
            tool_call_id=call_id,
        )
        for call_id in sorted(state["approval_call_ids"])
    ]
    events.append(
        TraceEvent(
            step=state["step_count"],
            event_type=TraceEventType.RUN_RESUMED,
            latency_ms=0,
        )
    )
    return {
        "approved": approved,
        "status": AgentStatus.RUNNING.value,
        "trace": _record(state, runtime.context, events),
    }


def execute_tools(
    state: AgentGraphState, runtime: Runtime[AgentRuntimeContext]
) -> dict[str, Any]:
    ctx = runtime.context
    approval_ids = frozenset(state["approval_call_ids"])
    granted = approval_ids if state["approved"] else frozenset()
    execution = ExecutionContext(
        user_id=ctx.user_id,
        is_superuser=ctx.is_superuser,
        approved_call_ids=granted,
    )
    tool_ctx = ToolContext(session=ctx.session, execution=execution)

    results: list[ToolResult] = []
    events: list[TraceEvent] = []
    evidence: list[dict[str, Any]] = []
    step = state["step_count"]
    executed = 0

    for raw in state["pending_calls"]:
        model_call = ModelToolCall.from_dict(raw)
        rejected = model_call.id in approval_ids and not state["approved"]
        started = monotonic()

        if rejected:
            # 用户拒绝：如实回给模型，且不计入工具预算。
            result = error_result(
                call_id=model_call.id,
                tool_name=model_call.name,
                error=UserRejectedError(f"用户拒绝执行工具 {model_call.name}"),
            )
            outcome = None
        else:
            executed += 1
            try:
                call = validate_tool_call(
                    registry=ctx.registry,
                    tool_name=model_call.name,
                    raw_arguments=model_call.arguments,
                    call_id=model_call.id,
                )
            except HarnessError as error:
                results.append(
                    error_result(
                        call_id=model_call.id, tool_name=model_call.name, error=error
                    )
                )
                events.append(_tool_event(step, model_call, results[-1], started, None))
                continue

            decision = decide(context=execution, call=call)
            outcome = decision.outcome
            if decision.outcome is PolicyOutcome.ALLOW:
                result = execute_tool(call=call, ctx=tool_ctx)
            else:
                result = error_result(
                    call_id=model_call.id,
                    tool_name=model_call.name,
                    error=PermissionDeniedError(
                        f"当前用户无权使用工具 {model_call.name}"
                    ),
                )

        results.append(result)
        events.append(_tool_event(step, model_call, result, started, outcome))
        if result.status == "ok" and result.output is not None:
            # 只有真的读成功了，这些证据才允许被引用。
            evidence.extend(
                extract_evidence(model_call.name, result.output.model_dump(mode="json"))
            )

    return {
        "messages": [ctx.model.tool_result_message(results)],
        "trace": _record(state, ctx, events),
        "evidence": evidence,
        "tool_call_count": state["tool_call_count"] + executed,
        "pending_calls": [],
        "approval_call_ids": [],
        "pending_confirmation": None,
        "approved": False,
    }


def _tool_event(
    step: int,
    model_call: ModelToolCall,
    result: ToolResult,
    started: float,
    outcome: PolicyOutcome | None,
) -> TraceEvent:
    return TraceEvent(
        step=step,
        event_type=TraceEventType.TOOL_CALL,
        latency_ms=int((monotonic() - started) * 1000),
        tool_name=model_call.name,
        tool_call_id=model_call.id,
        policy_outcome=outcome,
        tool_result_status=result.status,
        error_code=None if result.error is None else result.error.code,
    )


def finalize(
    state: AgentGraphState, runtime: Runtime[AgentRuntimeContext]
) -> dict[str, Any]:
    ctx = runtime.context
    trace = _record(
        state,
        ctx,
        [
            TraceEvent(
                step=state["step_count"],
                event_type=TraceEventType.RUN_FINISHED,
                latency_ms=0,
                final_status=state["status"],
            )
        ],
    )
    try:
        ctx.recorder.finish_run(_as_run_state(state, ctx))
    except Exception as error:  # noqa: BLE001 - 记录失败不能打断主流程
        logger.error(
            "run %s: could not close the run: %s",
            state["run_id"],
            type(error).__name__,
        )
    return {"trace": trace}


# --------------------------------------------------------------------------
# 条件边
# --------------------------------------------------------------------------


def route_after_model(state: AgentGraphState) -> str:
    if state["status"] != AgentStatus.RUNNING.value:
        return "finalize"
    return "route_tools"


def route_after_plan(state: AgentGraphState) -> str:
    return "human_approval" if state["approval_call_ids"] else "execute_tools"


def build_graph(checkpointer: Any = None) -> Any:
    builder = StateGraph(AgentGraphState, context_schema=AgentRuntimeContext)
    builder.add_node("call_model", call_model)
    builder.add_node("route_tools", route_tools)
    builder.add_node("human_approval", human_approval)
    builder.add_node("execute_tools", execute_tools)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "call_model")
    builder.add_conditional_edges(
        "call_model", route_after_model, ["route_tools", "finalize"]
    )
    builder.add_conditional_edges(
        "route_tools", route_after_plan, ["human_approval", "execute_tools"]
    )
    builder.add_edge("human_approval", "execute_tools")
    builder.add_edge("execute_tools", "call_model")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)
