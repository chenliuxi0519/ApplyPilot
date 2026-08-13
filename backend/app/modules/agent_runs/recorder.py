import uuid

from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.agent.state import AgentState, AgentStatus
from app.agent.trace import TraceEvent
from app.modules.agent_runs.models import OPEN_STATUSES, AgentRun, AgentRunEvent
from app.modules.columns import get_datetime_utc


class PostgresRunRecorder:
    def __init__(
        self,
        engine: Engine,
        *,
        store_final_answer: bool = True,
        run_engine: str | None = None,
    ) -> None:
        self._engine = engine
        self._store_final_answer = store_final_answer
        self._run_engine = run_engine

    def start_run(self, state: AgentState) -> None:
        now = get_datetime_utc()
        with Session(self._engine) as session:
            session.add(
                AgentRun(
                    id=state.run_id,
                    user_id=state.user_id,
                    status=AgentStatus.RUNNING,
                    engine=self._run_engine,
                    started_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

    def record_event(self, run_id: uuid.UUID, sequence: int, event: TraceEvent) -> None:
        with Session(self._engine) as session:
            session.add(
                AgentRunEvent(
                    run_id=run_id,
                    sequence=sequence,
                    step=event.step,
                    event_type=event.event_type,
                    stop_reason=None
                    if event.stop_reason is None
                    else event.stop_reason.value,
                    produced_tool_calls=event.produced_tool_calls,
                    tool_name=event.tool_name,
                    tool_call_id=event.tool_call_id,
                    policy_outcome=event.policy_outcome,
                    tool_result_status=event.tool_result_status,
                    error_code=event.error_code,
                    latency_ms=event.latency_ms,
                    final_status=event.final_status,
                    history_count=event.history_count,
                    estimated_tokens=event.estimated_tokens,
                    summarized=event.summarized,
                    profile_fields=event.profile_fields,
                )
            )
            session.commit()

    def finish_run(self, state: AgentState) -> None:
        with Session(self._engine) as session:
            run = session.get(AgentRun, state.run_id)
            if run is None:
                raise LookupError(f"No run {state.run_id} to finish")

            now = get_datetime_utc()
            run.status = state.status
            run.step_count = state.step_count
            run.tool_call_count = state.tool_call_count
            run.last_error_code = (
                None if state.last_error is None else state.last_error.code
            )
            if self._store_final_answer:
                run.final_answer = state.final_answer

            run.finished_at = None if state.status in OPEN_STATUSES else now
            run.updated_at = now
            session.add(run)
            session.commit()
