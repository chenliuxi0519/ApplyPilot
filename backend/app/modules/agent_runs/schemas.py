import uuid
from datetime import datetime
from typing import Any

from sqlmodel import SQLModel

from app.agent.state import AgentStatus
from app.agent.trace import TraceEventType
from app.harness import PolicyOutcome, ToolErrorCode


class RunMetricsPublic(SQLModel):
    task_success: bool
    total_steps: int
    total_tool_calls: int
    tool_error_count: int
    confirmation_count: int
    approval_count: int
    rejection_count: int
    total_tool_latency_ms: int
    run_duration_ms: int | None


class AgentRunPublic(SQLModel):
    id: uuid.UUID
    status: AgentStatus
    started_at: datetime
    finished_at: datetime | None
    step_count: int
    tool_call_count: int
    final_answer: str | None
    conversation_id: str | None
    user_message: str | None
    response_payload: dict[str, Any] | None
    last_error_code: ToolErrorCode | None


class AgentRunsPublic(SQLModel):
    data: list[AgentRunPublic]
    count: int


class AgentRunEventPublic(SQLModel):
    sequence: int
    step: int
    event_type: TraceEventType
    stop_reason: str | None
    produced_tool_calls: int | None
    tool_name: str | None
    tool_call_id: str | None
    policy_outcome: PolicyOutcome | None
    tool_result_status: str | None
    error_code: ToolErrorCode | None
    latency_ms: int | None
    final_status: str | None
    created_at: datetime


class AgentRunEventsPublic(SQLModel):
    data: list[AgentRunEventPublic]
    count: int


class AgentRunDetailPublic(AgentRunPublic):
    metrics: RunMetricsPublic
