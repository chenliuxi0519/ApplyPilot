from collections.abc import Callable, Sequence
from typing import Any

from app.agent.model import ModelResponse, ModelStopReason, ModelToolCall
from app.evaluation.case import FixtureData
from app.harness import ToolResult

Step = ModelResponse | Callable[[Sequence[ToolResult]], ModelResponse]
ScriptBuilder = Callable[[FixtureData], Sequence[Step]]

_REGISTRY: dict[str, ScriptBuilder] = {}


class UnknownScriptError(KeyError):
    pass


class ScriptExhaustedError(AssertionError):
    pass


def script(name: str) -> Callable[[ScriptBuilder], ScriptBuilder]:
    def register(builder: ScriptBuilder) -> ScriptBuilder:
        if name in _REGISTRY:
            raise ValueError(f"Script {name} is already registered")
        _REGISTRY[name] = builder
        return builder

    return register


def build_script(name: str, data: FixtureData) -> Sequence[Step]:
    if name not in _REGISTRY:
        raise UnknownScriptError(f"No script named {name}")
    return _REGISTRY[name](data)


def script_names() -> frozenset[str]:
    return frozenset(_REGISTRY)


class ScriptedModel:
    def __init__(self, steps: Sequence[Step]) -> None:
        self._steps = list(steps)
        self._index = 0
        self._last_results: tuple[ToolResult, ...] = ()

    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Any],
        tools: Sequence[dict[str, Any]],
    ) -> ModelResponse:
        del system, messages, tools
        if self._index >= len(self._steps):
            raise ScriptExhaustedError(
                f"The loop asked for step {self._index + 1} but the script has "
                f"{len(self._steps)}"
            )
        step = self._steps[self._index]
        self._index += 1

        if isinstance(step, ModelResponse):
            return step
        return step(self._last_results)

    def user_message(self, text: str) -> Any:
        return {"role": "user", "content": text}

    def tool_result_message(self, results: Sequence[ToolResult]) -> Any:

        self._last_results = tuple(results)
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": result.call_id,
                    "is_error": result.status == "error",
                }
                for result in results
            ],
        }


def answer(text: str) -> ModelResponse:
    return ModelResponse(
        stop_reason=ModelStopReason.END_TURN,
        text=text,
        tool_calls=(),
        assistant_message={"role": "assistant", "content": text},
    )


def calls(*tool_calls: ModelToolCall) -> ModelResponse:
    return ModelResponse(
        stop_reason=ModelStopReason.TOOL_USE,
        text=None,
        tool_calls=tool_calls,
        assistant_message={
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": call.arguments,
                }
                for call in tool_calls
            ],
        },
    )


def call(
    name: str, arguments: dict[str, Any], call_id: str = "toolu_1"
) -> ModelToolCall:
    return ModelToolCall(id=call_id, name=name, arguments=arguments)


def error_code_of(results: Sequence[ToolResult]) -> str | None:
    for result in results:
        if result.error is not None:
            return result.error.code.value
    return None
