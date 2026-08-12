import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from app.harness import ToolContext, ToolDefinition, ToolRegistry


class UiEventType(StrEnum):
    PROGRAMS = "programs"
    REQUIREMENTS = "requirements"
    COMPARISON = "comparison"


@dataclass(frozen=True)
class UiEvent:
    type: UiEventType
    data: dict[str, Any]


TOOL_TRACE_LABELS: dict[str, str] = {
    "get_user_profile": "已读取个人档案",
    "update_user_profile": "已更新个人档案",
    "search_programs": "已搜索项目库",
    "get_program_requirements": "已查询申请要求",
    "compare_programs": "已对比项目匹配度",
    "create_application": "已加入申请计划",
    "create_application_task": "已创建申请任务",
    "update_application_task": "已更新申请任务",
    "update_application_status": "已更新申请状态",
}


def trace_label(tool_name: str) -> str:
    return TOOL_TRACE_LABELS.get(tool_name, "已调用工具")


def _programs(output: BaseModel) -> UiEvent | None:
    payload = output.model_dump(mode="json")
    return UiEvent(
        type=UiEventType.PROGRAMS,
        data={
            "count": payload.get("count", 0),
            "programs": [
                {
                    "program_id": row["program_id"],
                    "name": row["name"],
                    "university": row["university"],
                    "region": row["region"],
                    "degree_type": row["degree_type"],
                    "field_tags": list(row.get("field_tags") or []),
                }
                for row in payload.get("data") or []
            ],
        },
    )


def _requirements(output: BaseModel) -> UiEvent | None:
    payload = output.model_dump(mode="json")
    rows = payload.get("data") or []
    if not rows:
        return None
    return UiEvent(
        type=UiEventType.REQUIREMENTS,
        data={
            "program_id": payload["program_id"],
            "requirements": [
                {
                    "field_name": row["field_name"],
                    "application_cycle": row["application_cycle"],
                    "value": row["value"],
                    "status": row["status"],
                    "source_url": row.get("source_url"),
                    "captured_at": row.get("captured_at"),
                }
                for row in rows
            ],
        },
    )


def _comparison(output: BaseModel) -> UiEvent | None:
    payload = output.model_dump(mode="json")
    fits = payload.get("data") or []
    if not fits:
        return None
    return UiEvent(
        type=UiEventType.COMPARISON,
        data={
            "count": payload.get("count", len(fits)),
            "profile_missing": list(payload.get("profile_missing") or []),
            "fits": [
                {
                    "program_id": fit["program_id"],
                    "name": fit["name"],
                    "university": fit["university"],
                    "application_cycle": fit.get("application_cycle"),
                    "band": fit["band"],
                    "disputed": bool(fit.get("disputed")),
                    "gaps": [
                        {
                            "field": factor["field"],
                            "required": factor["required"],
                            "have": factor["have"],
                            "delta": factor["delta"],
                        }
                        for factor in (fit.get("gaps") or [])
                    ],
                    "strengths": [
                        {
                            "field": factor["field"],
                            "required": factor["required"],
                            "have": factor["have"],
                            "delta": factor["delta"],
                        }
                        for factor in (fit.get("strengths") or [])
                    ],
                    "context": [
                        {"field": row["field"], "value": row["value"]}
                        for row in (fit.get("context") or [])
                    ],
                }
                for fit in fits
            ],
        },
    )


Projector = Callable[[BaseModel], UiEvent | None]


PROJECTORS: dict[str, Projector] = {
    "search_programs": _programs,
    "get_program_requirements": _requirements,
    "compare_programs": _comparison,
}


@dataclass
class UiEventCollector:
    events: list[UiEvent] = field(default_factory=list)

    def add(self, event: UiEvent | None) -> None:
        if event is not None:
            self.events.append(event)

    def as_dicts(self) -> list[dict[str, Any]]:
        return [{"type": event.type.value, "data": event.data} for event in self.events]


def _capturing(
    definition: ToolDefinition, projector: Projector, collector: UiEventCollector
) -> Any:
    inner = definition.handler

    def handler(ctx: ToolContext, payload: Any) -> BaseModel:
        output = inner(ctx, payload)
        collector.add(projector(output))
        return output

    return handler


def build_ui_registry(
    collector: UiEventCollector, definitions: Sequence[ToolDefinition]
) -> ToolRegistry:
    registry = ToolRegistry()
    for definition in definitions:
        projector = PROJECTORS.get(definition.name)
        if projector is None:
            registry.register(definition)
            continue
        registry.register(
            dataclasses.replace(
                definition, handler=_capturing(definition, projector, collector)
            )
        )
    return registry
