from collections.abc import Sequence
from typing import Any

from app.harness.errors import DuplicateToolError, UnknownToolError
from app.harness.models import ToolDefinition


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise DuplicateToolError(
                f"A tool named {definition.name!r} is already registered"
            )
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        definition = self._tools.get(name)
        if definition is None:
            raise UnknownToolError(f"Unknown tool {name!r}")
        return definition

    def try_get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list(self) -> Sequence[ToolDefinition]:
        return [self._tools[name] for name in sorted(self._tools)]

    def names(self) -> Sequence[str]:
        return sorted(self._tools)

    def llm_schemas(self) -> Sequence[dict[str, Any]]:
        return [definition.to_llm_schema() for definition in self.list()]

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
