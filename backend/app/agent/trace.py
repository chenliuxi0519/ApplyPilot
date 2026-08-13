from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from app.agent.model import ModelStopReason
from app.harness import PolicyOutcome, ToolErrorCode


class TraceEventType(StrEnum):
    MODEL_REQUEST = "model_request"
    TOOL_CALL = "tool_call"
    RUN_FINISHED = "run_finished"
    HUMAN_CONFIRMATION_REQUIRED = "human_confirmation_required"
    HUMAN_APPROVED = "human_approved"
    HUMAN_REJECTED = "human_rejected"
    RUN_RESUMED = "run_resumed"


@dataclass(frozen=True)
class TraceEvent:
    step: int
    event_type: TraceEventType
    latency_ms: int

    stop_reason: ModelStopReason | None = None
    produced_tool_calls: int | None = None

    tool_name: str | None = None
    tool_call_id: str | None = None
    policy_outcome: PolicyOutcome | None = None
    tool_result_status: Literal["ok", "error"] | None = None
    error_code: ToolErrorCode | None = None

    final_status: str | None = None

    # 上下文观测：只记数量，不记内容。
    history_count: int | None = None
    estimated_tokens: int | None = None
    summarized: bool | None = None
    profile_fields: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "event_type": self.event_type.value,
            "latency_ms": self.latency_ms,
            "stop_reason": None if self.stop_reason is None else self.stop_reason.value,
            "produced_tool_calls": self.produced_tool_calls,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "policy_outcome": None
            if self.policy_outcome is None
            else self.policy_outcome.value,
            "tool_result_status": self.tool_result_status,
            "error_code": None if self.error_code is None else self.error_code.value,
            "final_status": self.final_status,
            "history_count": self.history_count,
            "estimated_tokens": self.estimated_tokens,
            "summarized": self.summarized,
            "profile_fields": self.profile_fields,
        }
