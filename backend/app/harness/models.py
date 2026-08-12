import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel
from sqlmodel import Session

from app.harness.errors import HarnessError, ToolError, ToolErrorCode


class PermissionLevel(StrEnum):
    READ = "read"
    LOW_RISK_WRITE = "low_risk_write"
    HIGH_RISK_WRITE = "high_risk_write"
    ADMIN_WRITE = "admin_write"


_PERMISSION_RANK: dict[PermissionLevel, int] = {
    PermissionLevel.READ: 0,
    PermissionLevel.LOW_RISK_WRITE: 1,
    PermissionLevel.HIGH_RISK_WRITE: 2,
    PermissionLevel.ADMIN_WRITE: 3,
}


def max_permission(left: PermissionLevel, right: PermissionLevel) -> PermissionLevel:
    return left if _PERMISSION_RANK[left] >= _PERMISSION_RANK[right] else right


@dataclass(frozen=True)
class ExecutionContext:
    user_id: uuid.UUID
    is_superuser: bool = False

    approved_call_ids: frozenset[str] = field(default_factory=frozenset)

    def is_approved(self, call_id: str) -> bool:
        return call_id in self.approved_call_ids


@dataclass(frozen=True)
class ToolContext:
    session: Session
    execution: ExecutionContext

    @property
    def user_id(self) -> uuid.UUID:
        return self.execution.user_id


class ToolHandler(Protocol):
    def __call__(self, ctx: ToolContext, payload: Any) -> BaseModel: ...


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    permission_level: PermissionLevel
    handler: ToolHandler

    escalate: Callable[[BaseModel], PermissionLevel] | None = None

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    @property
    def output_schema(self) -> dict[str, Any]:
        return self.output_model.model_json_schema()

    def to_llm_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def effective_permission(self, payload: BaseModel) -> PermissionLevel:
        if self.escalate is None:
            return self.permission_level
        return max_permission(self.permission_level, self.escalate(payload))


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    tool_name: str
    raw_arguments: dict[str, Any]
    payload: BaseModel
    definition: ToolDefinition


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    tool_name: str
    status: Literal["ok", "error"]
    output: BaseModel | None = None
    error: ToolError | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.status == "ok":
            return {
                "call_id": self.call_id,
                "tool_name": self.tool_name,
                "status": self.status,
                "output": None
                if self.output is None
                else self.output.model_dump(mode="json"),
            }
        assert self.error is not None
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "error": {
                "code": self.error.code.value,
                "message": self.error.message,
                "details": self.error.details,
            },
        }


def success_result(*, call_id: str, tool_name: str, output: BaseModel) -> ToolResult:
    return ToolResult(call_id=call_id, tool_name=tool_name, status="ok", output=output)


def error_result(*, call_id: str, tool_name: str, error: HarnessError) -> ToolResult:
    return ToolResult(
        call_id=call_id,
        tool_name=tool_name,
        status="error",
        error=ToolError(code=error.code, message=error.message, details=error.details),
    )


def unexpected_result(*, call_id: str, tool_name: str, error: Exception) -> ToolResult:
    return ToolResult(
        call_id=call_id,
        tool_name=tool_name,
        status="error",
        error=ToolError(code=ToolErrorCode.INTERNAL, message=str(error), details=None),
    )
