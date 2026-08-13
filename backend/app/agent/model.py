from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from app.harness import ToolResult


class ModelStopReason(StrEnum):
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    REFUSAL = "refusal"
    OTHER = "other"


@dataclass(frozen=True)
class ModelToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": dict(self.arguments)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ModelToolCall":
        return cls(
            id=payload["id"],
            name=payload["name"],
            arguments=dict(payload["arguments"]),
        )


@dataclass(frozen=True)
class ModelResponse:
    stop_reason: ModelStopReason
    text: str | None
    tool_calls: tuple[ModelToolCall, ...]

    assistant_message: Any


class ModelClient(Protocol):
    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Any],
        tools: Sequence[dict[str, Any]],
    ) -> ModelResponse: ...

    def tool_result_message(self, results: Sequence[ToolResult]) -> Any: ...

    def user_message(self, text: str) -> Any: ...
