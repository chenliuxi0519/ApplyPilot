from collections.abc import Sequence
from dataclasses import dataclass

from app.agent.state import AgentStatus
from app.agent.trace import TraceEventType
from app.modules.agent_runs.models import AgentRun, AgentRunEvent


@dataclass(frozen=True)
class RunMetrics:
    task_success: bool
    total_steps: int
    total_tool_calls: int
    tool_error_count: int
    confirmation_count: int
    approval_count: int
    rejection_count: int
    total_tool_latency_ms: int
    run_duration_ms: int | None


def compute_metrics(run: AgentRun, events: Sequence[AgentRunEvent]) -> RunMetrics:
    tool_events = [
        event for event in events if event.event_type is TraceEventType.TOOL_CALL
    ]
    return RunMetrics(
        task_success=run.status is AgentStatus.COMPLETED,
        total_steps=run.step_count,
        total_tool_calls=len(tool_events),
        tool_error_count=sum(
            1 for event in tool_events if event.tool_result_status == "error"
        ),
        confirmation_count=_count(events, TraceEventType.HUMAN_CONFIRMATION_REQUIRED),
        approval_count=_count(events, TraceEventType.HUMAN_APPROVED),
        rejection_count=_count(events, TraceEventType.HUMAN_REJECTED),
        total_tool_latency_ms=sum(event.latency_ms or 0 for event in tool_events),
        run_duration_ms=_duration_ms(run),
    )


def _count(events: Sequence[AgentRunEvent], event_type: TraceEventType) -> int:
    return sum(1 for event in events if event.event_type is event_type)


def _duration_ms(run: AgentRun) -> int | None:
    if run.finished_at is None:
        return None
    return int((run.finished_at - run.started_at).total_seconds() * 1000)
