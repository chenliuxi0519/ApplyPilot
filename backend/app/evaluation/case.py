import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.agent.budget import Budget
from app.agent.state import AgentStatus
from app.harness import ToolErrorCode


class Category(StrEnum):
    PROFILE = "profile"
    PROGRAM_SEARCH = "program_search"
    PROGRAM_ANALYSIS = "program_analysis"
    APPLICATION = "application"
    HITL = "hitl"
    ERROR_RECOVERY = "error_recovery"


class ResumeDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class EffectKind(StrEnum):
    NO_CHANGE = "no_change"
    APPLICATION_COUNT = "application_count"
    APPLICATION_STATUS = "application_status"
    TASK_STATUS = "task_status"
    PROFILE_FIELD = "profile_field"


@dataclass(frozen=True)
class EffectCheck:
    kind: EffectKind
    params: Mapping[str, str | int] = field(default_factory=dict)

    def describe(self) -> str:
        if not self.params:
            return self.kind.value
        detail = ", ".join(
            f"{key}={value}" for key, value in sorted(self.params.items())
        )
        return f"{self.kind.value}({detail})"


NO_CHANGE = EffectCheck(kind=EffectKind.NO_CHANGE)


class _Missing(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    category: Category
    user_message: str
    setup: str
    script: str | None = None
    expected_tools: frozenset[str] = frozenset()
    expected_tool_order: tuple[str, ...] = ()
    forbidden_tools: frozenset[str] = frozenset()
    expected_final_status: AgentStatus = AgentStatus.COMPLETED
    expect_confirmation: bool = False
    resume: ResumeDecision | None = None
    expected_error_codes: frozenset[ToolErrorCode] = frozenset()
    effect_at_pause: EffectCheck | None = None
    expected_effect: EffectCheck = NO_CHANGE
    budget: Budget | None = None
    real: bool = False
    notes: str = ""

    def render_message(self, values: Mapping[str, Any]) -> str:
        return self.user_message.format_map(_Missing(values))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category.value,
            "user_message": self.user_message,
            "setup": self.setup,
            "script": self.script,
            "expected_tools": sorted(self.expected_tools),
            "expected_tool_order": list(self.expected_tool_order),
            "forbidden_tools": sorted(self.forbidden_tools),
            "expected_final_status": self.expected_final_status.value,
            "expect_confirmation": self.expect_confirmation,
            "resume": None if self.resume is None else self.resume.value,
            "expected_error_codes": sorted(
                code.value for code in self.expected_error_codes
            ),
            "effect_at_pause": None
            if self.effect_at_pause is None
            else self.effect_at_pause.describe(),
            "expected_effect": self.expected_effect.describe(),
            "budget": None
            if self.budget is None
            else {
                "max_steps": self.budget.max_steps,
                "max_tool_calls": self.budget.max_tool_calls,
            },
            "real": self.real,
            "notes": self.notes,
        }


@dataclass
class FixtureData:
    user_id: uuid.UUID
    values: dict[str, Any] = field(default_factory=dict)

    def id_of(self, key: str) -> uuid.UUID:
        value = self.values[key]
        assert isinstance(value, uuid.UUID)
        return value

    def version_of(self, key: str) -> int:
        value = self.values[key]
        assert isinstance(value, int)
        return value

    def text_of(self, key: str) -> str:
        value = self.values[key]
        assert isinstance(value, str)
        return value
