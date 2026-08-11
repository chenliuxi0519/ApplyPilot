import json
from collections.abc import Sequence
from typing import Any, cast

import anthropic
from anthropic.types import MessageParam, ToolChoiceAutoParam, ToolUnionParam

from app.agent.model import ModelResponse, ModelStopReason, ModelToolCall
from app.core.config import settings
from app.harness import ToolResult

DEFAULT_MAX_TOKENS = 8192

_STOP_REASONS = {
    "end_turn": ModelStopReason.END_TURN,
    "tool_use": ModelStopReason.TOOL_USE,
    "max_tokens": ModelStopReason.MAX_TOKENS,
    "refusal": ModelStopReason.REFUSAL,
}


class AgentNotConfiguredError(RuntimeError):
    pass


class AnthropicModelClient:
    def __init__(
        self,
        *,
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:

        self._client = client or anthropic.Anthropic(
            api_key=_required("AGENT_API_KEY"),
            base_url=_required("AGENT_BASE_URL"),
        )
        self._model = model or settings.AGENT_MODEL
        self._max_tokens = max_tokens

    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Any],
        tools: Sequence[dict[str, Any]],
    ) -> ModelResponse:

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=cast(list[MessageParam], list(messages)),
            tools=cast(list[ToolUnionParam], list(tools)),
            tool_choice=ToolChoiceAutoParam(type="auto"),
        )
        return self._normalize(response)

    def _normalize(self, response: Any) -> ModelResponse:
        text_parts: list[str] = []
        tool_calls: list[ModelToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ModelToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input),
                    )
                )
        return ModelResponse(
            stop_reason=_STOP_REASONS.get(
                response.stop_reason or "", ModelStopReason.OTHER
            ),
            text="\n".join(text_parts) if text_parts else None,
            tool_calls=tuple(tool_calls),
            assistant_message={"role": "assistant", "content": response.content},
        )

    def user_message(self, text: str) -> Any:
        return {"role": "user", "content": text}

    def tool_result_message(self, results: Sequence[ToolResult]) -> Any:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": result.call_id,
                    "content": _encode(result),
                    "is_error": result.status == "error",
                }
                for result in results
            ],
        }


def _required(name: str) -> str:
    value = getattr(settings, name, None)
    if not value:
        raise AgentNotConfiguredError(
            f"{name} 未配置。Agent 需要同时配置 AGENT_BASE_URL、"
            "AGENT_API_KEY 和 AGENT_MODEL。"
        )
    return str(value)


def _encode(result: ToolResult) -> str:
    payload = result.to_dict()
    return json.dumps(
        payload.get("output") if result.status == "ok" else payload.get("error"),
        ensure_ascii=False,
        default=str,
    )
