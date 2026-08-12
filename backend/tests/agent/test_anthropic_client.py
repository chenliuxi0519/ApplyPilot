from typing import Any

from app.agent.anthropic_client import AnthropicModelClient
from app.agent.model import ModelStopReason
from app.core.config import settings
from app.harness import ToolErrorCode, ToolExecutionError
from app.harness.models import error_result, success_result
from app.tools import build_default_registry
from tests.harness.conftest import EchoOutput


class _Block:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class _Response:
    def __init__(self, content: list[Any], stop_reason: str | None) -> None:
        self.content = content
        self.stop_reason = stop_reason


class _RecordingMessages:
    def __init__(self, response: _Response) -> None:
        self._response = response
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> _Response:
        self.kwargs = kwargs
        return self._response


class _RecordingClient:
    def __init__(self, response: _Response) -> None:
        self.messages = _RecordingMessages(response)


def _client(response: _Response) -> tuple[AnthropicModelClient, _RecordingClient]:
    recording = _RecordingClient(response)
    return AnthropicModelClient(client=recording), recording  # type: ignore[arg-type]


def test_request_omits_parameters_current_models_reject() -> None:
    client, recording = _client(_Response([], "end_turn"))
    client.complete(system="s", messages=[], tools=[])

    for rejected in ("temperature", "top_p", "top_k", "budget_tokens"):
        assert rejected not in recording.messages.kwargs


def test_request_uses_the_configured_model_and_auto_tool_choice() -> None:
    client, recording = _client(_Response([], "end_turn"))
    client.complete(system="s", messages=[], tools=[])

    assert recording.messages.kwargs["model"] == settings.AGENT_MODEL
    assert recording.messages.kwargs["tool_choice"] == {"type": "auto"}
    assert recording.messages.kwargs["max_tokens"] > 0


def test_registry_schemas_pass_through_unchanged() -> None:
    tools = list(build_default_registry().llm_schemas())
    client, recording = _client(_Response([], "end_turn"))
    client.complete(system="s", messages=[], tools=tools)

    assert recording.messages.kwargs["tools"] == tools


def test_text_response_is_normalized() -> None:
    client, _ = _client(_Response([_Block(type="text", text="hello")], "end_turn"))
    response = client.complete(system="s", messages=[], tools=[])

    assert response.stop_reason is ModelStopReason.END_TURN
    assert response.text == "hello"
    assert response.tool_calls == ()


def test_tool_use_response_is_normalized() -> None:
    client, _ = _client(
        _Response(
            [
                _Block(type="text", text="looking"),
                _Block(
                    type="tool_use",
                    id="toolu_1",
                    name="search_programs",
                    input={"region": "singapore"},
                ),
            ],
            "tool_use",
        )
    )
    response = client.complete(system="s", messages=[], tools=[])

    assert response.stop_reason is ModelStopReason.TOOL_USE
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "toolu_1"
    assert response.tool_calls[0].name == "search_programs"
    assert response.tool_calls[0].arguments == {"region": "singapore"}


def test_refusal_is_normalized_rather_than_retried() -> None:
    client, _ = _client(_Response([], "refusal"))
    response = client.complete(system="s", messages=[], tools=[])
    assert response.stop_reason is ModelStopReason.REFUSAL


def test_unknown_stop_reason_falls_back_to_other() -> None:
    client, _ = _client(_Response([], "something_new"))
    assert (
        client.complete(system="s", messages=[], tools=[]).stop_reason
        is ModelStopReason.OTHER
    )


def test_assistant_message_replays_content_verbatim() -> None:
    blocks = [_Block(type="text", text="hi")]
    client, _ = _client(_Response(blocks, "end_turn"))
    response = client.complete(system="s", messages=[], tools=[])

    assert response.assistant_message["role"] == "assistant"
    assert response.assistant_message["content"] is blocks


def test_every_result_of_one_turn_goes_in_a_single_message() -> None:
    client, _ = _client(_Response([], "end_turn"))
    message = client.tool_result_message(
        [
            success_result(call_id="a", tool_name="t", output=EchoOutput(echoed="x")),
            error_result(
                call_id="b",
                tool_name="t",
                error=ToolExecutionError(ToolErrorCode.NOT_FOUND, "gone"),
            ),
        ]
    )

    assert message["role"] == "user"
    assert [block["tool_use_id"] for block in message["content"]] == ["a", "b"]
    assert message["content"][0]["is_error"] is False
    assert message["content"][1]["is_error"] is True
    assert "not_found" in message["content"][1]["content"]
