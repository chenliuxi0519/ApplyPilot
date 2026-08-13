"""Agent 的多步执行、暂停确认和恢复入口。"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import monotonic

from sqlmodel import Session

from app.agent.budget import Budget
from app.agent.model import ModelClient, ModelResponse, ModelStopReason, ModelToolCall
from app.agent.prompt import SYSTEM_PROMPT
from app.agent.recorder import NullRunRecorder, RunRecorder
from app.agent.state import (
    AgentState,
    AgentStatus,
    PendingBatch,
    PendingConfirmation,
)
from app.agent.trace import TraceEvent, TraceEventType
from app.harness import (
    ExecutionContext,
    HarnessError,
    PermissionDeniedError,
    PolicyOutcome,
    ToolCall,
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


class ResumeNotPendingError(RuntimeError):
    pass


class RunAlreadyStartedError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Planned:
    model_call: ModelToolCall
    call: ToolCall | None = None
    rejection: HarnessError | None = None
    policy_outcome: PolicyOutcome | None = None
    confirmation: PendingConfirmation | None = None


class AgentLoop:
    def __init__(
        self,
        *,
        model: ModelClient,
        registry: ToolRegistry,
        session: Session,
        execution: ExecutionContext,
        budget: Budget | None = None,
        system_prompt: str = SYSTEM_PROMPT,
        recorder: RunRecorder | None = None,
    ) -> None:
        self._model = model
        self._registry = registry
        self._session = session
        self._execution = execution
        self._budget = budget or Budget()
        self._system_prompt = system_prompt
        self._recorder = recorder or NullRunRecorder()

    def run(self, state: AgentState, user_message: str) -> AgentState:
        if state.trace:
            raise RunAlreadyStartedError(
                "该运行状态已经使用过，新问题需要创建新的运行状态"
            )
        self._start(state)
        state.messages.append(self._model.user_message(user_message))
        state.status = AgentStatus.RUNNING
        return self._loop(state)

    def resume_approved(self, state: AgentState) -> AgentState:
        batch = self._take_pending(state, TraceEventType.HUMAN_APPROVED)
        return self._replay(
            state,
            batch,
            approved=batch.confirmation_call_ids,
            rejected=frozenset(),
        )

    def resume_rejected(self, state: AgentState) -> AgentState:
        batch = self._take_pending(state, TraceEventType.HUMAN_REJECTED)
        return self._replay(
            state,
            batch,
            approved=frozenset(),
            rejected=batch.confirmation_call_ids,
        )

    def _take_pending(
        self, state: AgentState, decision: TraceEventType
    ) -> PendingBatch:
        if state.status is not AgentStatus.WAITING_CONFIRMATION:
            raise ResumeNotPendingError(f"当前运行状态 {state.status.value} 不能继续")
        if state.pending_batch is None:
            raise ResumeNotPendingError("当前运行没有等待确认的工具调用")

        batch = state.pending_batch
        for call_id in sorted(batch.confirmation_call_ids):
            self._emit(
                state,
                TraceEvent(
                    step=state.step_count,
                    event_type=decision,
                    latency_ms=0,
                    tool_name=_name_of(batch, call_id),
                    tool_call_id=call_id,
                ),
            )
        # 执行前先清空待确认批次，保证重复点击也只能恢复一次。
        state.pending_batch = None
        state.pending_confirmation = None
        state.status = AgentStatus.RUNNING
        return batch

    def _loop(self, state: AgentState) -> AgentState:
        while True:
            if self._budget.steps_exhausted(state.step_count):
                return self._finish(state, AgentStatus.BUDGET_EXCEEDED)
            state.step_count += 1

            response = self._call_model(state)
            state.messages.append(response.assistant_message)

            if response.stop_reason is ModelStopReason.REFUSAL:
                state.last_error = _internal_error("模型拒绝了本次请求")
                return self._finish(state, AgentStatus.FAILED)
            if response.stop_reason is ModelStopReason.MAX_TOKENS:
                state.last_error = _internal_error("模型回答达到输出长度上限")
                return self._finish(state, AgentStatus.FAILED)

            if not response.tool_calls:
                state.final_answer = response.text
                return self._finish(state, AgentStatus.COMPLETED)

            if self._budget.would_exceed_tool_calls(
                state.tool_call_count, len(response.tool_calls)
            ):
                return self._finish(state, AgentStatus.BUDGET_EXCEEDED)

            planned = self._plan(response.tool_calls)
            confirmations = [item for item in planned if item.confirmation]
            if confirmations:
                # 一批调用中只要有高风险操作就整批暂停，避免出现只执行一半的对话。
                return self._pause(state, response.tool_calls, confirmations)

            results = [self._run_one(state, item) for item in planned]
            state.messages.append(self._model.tool_result_message(results))

    def _replay(
        self,
        state: AgentState,
        batch: PendingBatch,
        *,
        approved: frozenset[str],
        rejected: frozenset[str],
    ) -> AgentState:
        planned = self._plan(batch.model_calls, extra_approved=approved)
        results = [
            self._rejected_result(state, item)
            if item.model_call.id in rejected
            else self._run_one(state, item)
            for item in planned
        ]
        state.messages.append(self._model.tool_result_message(results))
        self._emit(
            state,
            TraceEvent(
                step=state.step_count,
                event_type=TraceEventType.RUN_RESUMED,
                latency_ms=0,
            ),
        )
        return self._loop(state)

    def _call_model(self, state: AgentState) -> ModelResponse:
        started = monotonic()
        response = self._model.complete(
            system=self._system_prompt,
            messages=state.messages,
            tools=list(self._registry.llm_schemas()),
        )
        self._emit(
            state,
            TraceEvent(
                step=state.step_count,
                event_type=TraceEventType.MODEL_REQUEST,
                latency_ms=_elapsed_ms(started),
                stop_reason=response.stop_reason,
                produced_tool_calls=len(response.tool_calls),
            ),
        )
        return response

    def _plan(
        self,
        model_calls: Sequence[ModelToolCall],
        *,
        extra_approved: frozenset[str] = frozenset(),
    ) -> list[_Planned]:
        context = self._context_with(extra_approved)
        planned: list[_Planned] = []
        for model_call in model_calls:
            try:
                call = validate_tool_call(
                    registry=self._registry,
                    tool_name=model_call.name,
                    raw_arguments=model_call.arguments,
                    call_id=model_call.id,
                )
            except HarnessError as error:
                planned.append(_Planned(model_call=model_call, rejection=error))
                continue

            decision = decide(context=context, call=call)
            confirmation = None
            if decision.outcome is PolicyOutcome.REQUIRE_HUMAN_CONFIRMATION:
                confirmation = PendingConfirmation(
                    call_id=call.call_id,
                    tool_name=call.tool_name,
                    permission_level=decision.permission_level,
                    reason=decision.reason,
                    arguments=dict(model_call.arguments),
                )
            planned.append(
                _Planned(
                    model_call=model_call,
                    call=call,
                    policy_outcome=decision.outcome,
                    confirmation=confirmation,
                )
            )
        return planned

    def _run_one(self, state: AgentState, item: _Planned) -> ToolResult:
        state.tool_call_count += 1
        started = monotonic()

        if item.rejection is not None:
            result = error_result(
                call_id=item.model_call.id,
                tool_name=item.model_call.name,
                error=item.rejection,
            )
        elif item.call is None or item.policy_outcome is PolicyOutcome.DENY:
            result = error_result(
                call_id=item.model_call.id,
                tool_name=item.model_call.name,
                error=PermissionDeniedError(
                    f"当前用户无权使用工具 {item.model_call.name}"
                ),
            )
        else:
            result = execute_tool(call=item.call, ctx=self._tool_context())

        self._trace_tool(state, item, result, _elapsed_ms(started))
        return result

    def _rejected_result(self, state: AgentState, item: _Planned) -> ToolResult:
        result = error_result(
            call_id=item.model_call.id,
            tool_name=item.model_call.name,
            error=UserRejectedError(f"用户拒绝执行工具 {item.model_call.name}"),
        )
        self._trace_tool(state, item, result, 0)
        return result

    def _pause(
        self,
        state: AgentState,
        model_calls: Sequence[ModelToolCall],
        confirmations: Sequence[_Planned],
    ) -> AgentState:
        state.pending_batch = PendingBatch(
            model_calls=tuple(model_calls),
            confirmation_call_ids=frozenset(
                item.model_call.id for item in confirmations
            ),
        )
        state.pending_confirmation = confirmations[0].confirmation
        for item in confirmations:
            self._emit(
                state,
                TraceEvent(
                    step=state.step_count,
                    event_type=TraceEventType.HUMAN_CONFIRMATION_REQUIRED,
                    latency_ms=0,
                    tool_name=item.model_call.name,
                    tool_call_id=item.model_call.id,
                    policy_outcome=item.policy_outcome,
                ),
            )
        return self._finish(state, AgentStatus.WAITING_CONFIRMATION)

    def _finish(self, state: AgentState, status: AgentStatus) -> AgentState:
        state.status = status
        self._emit(
            state,
            TraceEvent(
                step=state.step_count,
                event_type=TraceEventType.RUN_FINISHED,
                latency_ms=0,
                final_status=status.value,
            ),
        )
        self._persist_run(state)
        return state

    def _emit(self, state: AgentState, event: TraceEvent) -> None:
        state.trace.append(event)
        self._safely(
            state,
            lambda: self._recorder.record_event(
                state.run_id, len(state.trace) - 1, event
            ),
        )

    def _start(self, state: AgentState) -> None:
        self._safely(state, lambda: self._recorder.start_run(state))

    def _persist_run(self, state: AgentState) -> None:
        self._safely(state, lambda: self._recorder.finish_run(state))

    def _safely(self, state: AgentState, write: Callable[[], None]) -> None:
        try:
            write()
        except Exception as error:  # noqa: BLE001 - 记录失败不能打断主流程
            # 运行记录失败不能回滚已经完成的业务操作，但必须留下错误供排查。
            state.observability_failures += 1
            state.last_observability_error = str(error)
            # 只记异常类型：数据库异常的 str() 会带上 SQL 与绑定参数，
            # 而这些参数里可能有对话内容，不能进日志系统。
            logger.error(
                "run %s: could not record execution history: %s",
                state.run_id,
                type(error).__name__,
            )
            logger.debug("run %s: recorder failure detail", state.run_id, exc_info=True)

    def _context_with(self, extra_approved: frozenset[str]) -> ExecutionContext:
        if not extra_approved:
            return self._execution
        return ExecutionContext(
            user_id=self._execution.user_id,
            is_superuser=self._execution.is_superuser,
            approved_call_ids=self._execution.approved_call_ids | extra_approved,
        )

    def _tool_context(self) -> ToolContext:
        return ToolContext(session=self._session, execution=self._execution)

    def _trace_tool(
        self,
        state: AgentState,
        item: _Planned,
        result: ToolResult,
        latency_ms: int,
    ) -> None:
        self._emit(
            state,
            TraceEvent(
                step=state.step_count,
                event_type=TraceEventType.TOOL_CALL,
                latency_ms=latency_ms,
                tool_name=item.model_call.name,
                tool_call_id=item.model_call.id,
                policy_outcome=item.policy_outcome,
                tool_result_status=result.status,
                error_code=None if result.error is None else result.error.code,
            ),
        )


def _name_of(batch: PendingBatch, call_id: str) -> str | None:
    return next((call.name for call in batch.model_calls if call.id == call_id), None)


def _elapsed_ms(started: float) -> int:
    return int((monotonic() - started) * 1000)


def _internal_error(message: str) -> ToolError:
    return ToolError(code=ToolErrorCode.INTERNAL, message=message)
