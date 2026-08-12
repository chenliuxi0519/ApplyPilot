import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.agent.model import ModelToolCall
from app.agent.trace import TraceEvent
from app.harness import PermissionLevel, ToolError


class AgentStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    WAITING_CONFIRMATION = "waiting_confirmation"
    FAILED = "failed"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass(frozen=True)
class PendingConfirmation:
    call_id: str
    tool_name: str
    permission_level: PermissionLevel
    reason: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class PendingBatch:
    model_calls: tuple[ModelToolCall, ...]
    confirmation_call_ids: frozenset[str]


@dataclass
class AgentState:
    run_id: uuid.UUID
    user_id: uuid.UUID
    messages: list[Any] = field(default_factory=list)
    status: AgentStatus = AgentStatus.RUNNING
    step_count: int = 0
    tool_call_count: int = 0
    final_answer: str | None = None
    last_error: ToolError | None = None

    pending_confirmation: PendingConfirmation | None = None
    pending_batch: PendingBatch | None = None
    trace: list[TraceEvent] = field(default_factory=list)

    observability_failures: int = 0
    last_observability_error: str | None = None

    @classmethod
    def new(
        cls, *, user_id: uuid.UUID, messages: list[Any] | None = None
    ) -> "AgentState":
        return cls(
            run_id=uuid.uuid4(),
            user_id=user_id,
            messages=list(messages) if messages else [],
        )

    def trace_dicts(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.trace]
