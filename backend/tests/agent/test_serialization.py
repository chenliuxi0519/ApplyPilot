"""适配层把 provider 的 content block 转成中立纯 dict。

这是 checkpoint 能落库的前提：LangGraph 存的是纯 JSON，而 SDK 给的是对象。
转换必须无损——工具调用的 id/name/input 和文本内容都不能变，
而且换回去还要能被 Anthropic Messages API 接受。
"""

import json
import uuid
from types import SimpleNamespace
from typing import Any

from anthropic.types import TextBlock, ToolUseBlock
from pydantic import BaseModel

from app.agent.anthropic_client import AnthropicModelClient, _plain_blocks
from app.agent.model import ModelStopReason, ModelToolCall
from app.agent.state import AgentState, PendingConfirmation
from app.harness import PermissionLevel

# 覆盖中文、emoji、CJK 扩展、组合字符、RTL、零宽字符和换行。
UNICODE_SAMPLES = [
    "我想申请计算机科学硕士",
    "GPA 3.8/4.0，托福 105 分 🎓",
    "Ünïcödé ﬁ ligature",
    "𠮷野家の𩸽",
    "égalité",
    "مرحبا",
    "zero​width",
    "第一行\n第二行\t制表",
]


def _client() -> AnthropicModelClient:
    return AnthropicModelClient(
        client=SimpleNamespace(),  # type: ignore[arg-type]
        model="test-model",
    )


def _normalize(*blocks: Any, stop_reason: str = "tool_use") -> Any:
    response = SimpleNamespace(content=list(blocks), stop_reason=stop_reason)
    return _client()._normalize(response)


# --------------------------------------------------------------------------
# content block -> 纯 dict
# --------------------------------------------------------------------------


def test_a_text_block_becomes_a_plain_dict() -> None:
    response = _normalize(TextBlock(type="text", text="你好"), stop_reason="end_turn")

    assert response.assistant_message["content"] == [{"type": "text", "text": "你好"}]


def test_a_tool_use_block_keeps_id_name_and_input() -> None:
    response = _normalize(
        ToolUseBlock(
            type="tool_use",
            id="toolu_01ABC",
            name="search_programs",
            input={"university": "ETH", "limit": 5},
        )
    )

    assert response.assistant_message["content"] == [
        {
            "type": "tool_use",
            "id": "toolu_01ABC",
            "name": "search_programs",
            "input": {"university": "ETH", "limit": 5},
        }
    ]


def test_several_blocks_keep_their_order() -> None:
    response = _normalize(
        TextBlock(type="text", text="先看看你的档案"),
        ToolUseBlock(type="tool_use", id="toolu_1", name="get_user_profile", input={}),
        TextBlock(type="text", text="再搜项目"),
        ToolUseBlock(
            type="tool_use", id="toolu_2", name="search_programs", input={"q": "CS"}
        ),
    )

    content = response.assistant_message["content"]
    assert [block["type"] for block in content] == [
        "text",
        "tool_use",
        "text",
        "tool_use",
    ]
    assert [b["id"] for b in content if b["type"] == "tool_use"] == [
        "toolu_1",
        "toolu_2",
    ]
    assert response.text == "先看看你的档案\n再搜项目"


def test_an_empty_text_block_survives() -> None:
    response = _normalize(TextBlock(type="text", text=""), stop_reason="end_turn")

    assert response.assistant_message["content"] == [{"type": "text", "text": ""}]


def test_a_tool_use_with_no_arguments_survives() -> None:
    response = _normalize(
        ToolUseBlock(type="tool_use", id="toolu_1", name="get_user_profile", input={})
    )

    assert response.assistant_message["content"][0]["input"] == {}


def test_optional_fields_the_sdk_leaves_empty_are_dropped() -> None:
    """SDK 补出来的空字段不该回传给接口。"""
    block = TextBlock(type="text", text="hi")
    assert "citations" in block.model_dump()

    assert _plain_blocks([block]) == [{"type": "text", "text": "hi"}]


def test_unicode_text_is_unchanged() -> None:
    for sample in UNICODE_SAMPLES:
        response = _normalize(
            TextBlock(type="text", text=sample), stop_reason="end_turn"
        )
        assert response.assistant_message["content"][0]["text"] == sample


def test_unicode_inside_tool_arguments_is_unchanged() -> None:
    arguments: dict[str, Any] = {
        "note": "想去苏黎世联邦理工 🇨🇭",
        "list": ["数学", "统计"],
    }
    response = _normalize(
        ToolUseBlock(
            type="tool_use", id="toolu_1", name="update_user_profile", input=arguments
        )
    )

    assert response.assistant_message["content"][0]["input"] == arguments
    assert response.tool_calls[0].arguments == arguments


def test_blocks_that_are_already_dicts_are_copied_not_shared() -> None:
    original = {"type": "text", "text": "已经是 dict"}

    blocks = _plain_blocks([original])

    assert blocks == [original]
    assert blocks[0] is not original


# --------------------------------------------------------------------------
# 转换结果仍是 provider 能接受的形状
# --------------------------------------------------------------------------


def test_every_block_still_validates_as_a_provider_block() -> None:
    """纯 dict 换回 SDK 模型必须成立，否则发回去会被接口拒绝。"""
    response = _normalize(
        TextBlock(type="text", text="申请 ETH 的截止日期是什么"),
        ToolUseBlock(
            type="tool_use",
            id="toolu_1",
            name="get_program_requirements",
            input={"program_id": "p-1"},
        ),
    )

    models: dict[str, type[BaseModel]] = {
        "text": TextBlock,
        "tool_use": ToolUseBlock,
    }
    for block in response.assistant_message["content"]:
        restored = models[block["type"]].model_validate(block)
        assert restored.model_dump(mode="json", exclude_none=True) == block


def test_an_assistant_message_survives_a_json_round_trip() -> None:
    response = _normalize(
        TextBlock(type="text", text="让我查一下 🎓"),
        ToolUseBlock(
            type="tool_use", id="toolu_1", name="search_programs", input={"q": "CS"}
        ),
    )
    message = response.assistant_message

    assert json.loads(json.dumps(message)) == message
    assert json.loads(json.dumps(message, ensure_ascii=False)) == message


def test_a_tool_result_message_is_plain_json() -> None:
    message = _client().tool_result_message([])

    assert json.loads(json.dumps(message)) == message
    assert message["role"] == "user"


def test_a_user_message_is_plain_json() -> None:
    message = _client().user_message("我想申请 2026 年秋季入学 🎓")

    assert json.loads(json.dumps(message)) == message


# --------------------------------------------------------------------------
# 转换结果进入运行状态
# --------------------------------------------------------------------------


def build_transcript() -> list[dict[str, Any]]:
    """一段带工具调用的完整对话，供 checkpoint 用例复用。"""
    client = _client()
    response = _normalize(
        TextBlock(type="text", text="好的，我来把它标记为已提交 🎓"),
        ToolUseBlock(
            type="tool_use",
            id="toolu_01ABC",
            name="update_application_status",
            input={"target_status": "submitted", "备注": "已寄出材料"},
        ),
    )
    return [
        client.user_message("把我的 ETH 申请标记为已提交"),
        response.assistant_message,
        client.tool_result_message([]),
    ]


def test_a_transcript_goes_into_the_state_as_plain_json() -> None:
    state = AgentState.new(user_id=uuid.uuid4(), messages=build_transcript())

    assert json.loads(json.dumps(state.messages)) == state.messages
    assert all(isinstance(message, dict) for message in state.messages)


def test_the_state_never_holds_a_provider_object() -> None:
    state = AgentState.new(user_id=uuid.uuid4(), messages=build_transcript())

    for message in state.messages:
        content = message["content"]
        if isinstance(content, list):
            assert all(isinstance(block, dict) for block in content)


def test_the_stop_reason_is_still_normalized() -> None:
    assert (
        _normalize(
            TextBlock(type="text", text="hi"), stop_reason="end_turn"
        ).stop_reason
        is ModelStopReason.END_TURN
    )
    assert _normalize(TextBlock(type="text", text="hi")).stop_reason is (
        ModelStopReason.TOOL_USE
    )


def test_the_normalized_call_and_the_message_describe_one_call() -> None:
    response = _normalize(
        ToolUseBlock(
            type="tool_use", id="toolu_9", name="get_user_profile", input={"a": 1}
        )
    )

    assert response.tool_calls == (
        ModelToolCall(id="toolu_9", name="get_user_profile", arguments={"a": 1}),
    )
    block = response.assistant_message["content"][0]
    assert (block["id"], block["name"], block["input"]) == (
        "toolu_9",
        "get_user_profile",
        {"a": 1},
    )


# --------------------------------------------------------------------------
# 编排层自己的小结构
# --------------------------------------------------------------------------


def test_a_model_tool_call_round_trips() -> None:
    call = ModelToolCall(
        id="toolu_1", name="update_user_profile", arguments={"目标专业": "CS"}
    )

    assert ModelToolCall.from_dict(call.to_dict()) == call


def test_a_pending_confirmation_round_trips() -> None:
    pending = PendingConfirmation(
        call_id="toolu_1",
        tool_name="update_application_status",
        permission_level=PermissionLevel.HIGH_RISK_WRITE,
        reason="高风险修改需要用户确认",
        arguments={"target_status": "submitted", "version": 3},
    )

    restored = PendingConfirmation.from_dict(pending.to_dict())

    assert restored == pending
    assert restored.permission_level is PermissionLevel.HIGH_RISK_WRITE


def test_these_small_structures_are_json_safe() -> None:
    call = ModelToolCall(id="toolu_1", name="t", arguments={"中文": "值"})

    assert json.loads(json.dumps(call.to_dict())) == call.to_dict()
