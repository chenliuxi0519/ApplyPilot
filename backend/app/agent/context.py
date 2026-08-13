"""组装每次模型调用真正看到的上下文，并在历史过长时裁剪。

checkpoint 里始终保留完整历史；这里只决定"这一轮送多少给模型"。

关于消息形状：本模块是编排层唯一知道消息外层信封（role、tool_result 块）
的地方，而且只看信封不看内容——裁剪必须保证 tool_use 和 tool_result 成对，
否则发回去的历史是非法的。
"""

from dataclasses import dataclass
from typing import Any

# 模型输入里至少保留这么多条最近消息的原文。
DEFAULT_KEEP_RECENT = 12
# 未被摘要覆盖的消息超过这个条数，才触发一次摘要——不是每轮都摘要。
DEFAULT_SUMMARY_THRESHOLD = 24
# 粗略按 4 字符 ≈ 1 token 估算，只用于 trace 观测，不参与裁剪决策。
CHARS_PER_TOKEN = 4

SUMMARY_SYSTEM_PROMPT = """\
你在压缩一段留学申请咨询的对话历史，供后续轮次参考。

只总结对话语义：用户想申请什么、已经比较过哪些项目、当前进行到哪一步、
用户明确说过的重要条件和排除项。

不要复述 GPA、语言成绩、申请状态这类结构化事实——它们以数据库为准，
会另行提供。不要编造没出现过的内容。用简体中文，控制在 200 字以内。
"""


@dataclass(frozen=True)
class ContextBudget:
    keep_recent: int = DEFAULT_KEEP_RECENT
    summary_threshold: int = DEFAULT_SUMMARY_THRESHOLD


def _is_user(message: Any) -> bool:
    return isinstance(message, dict) and message.get("role") == "user"


def _carries_tool_result(message: Any) -> bool:
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return False
    return any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in content
    )


def safe_cut(messages: list[Any], desired: int) -> int:
    """把切点挪到一个合法的边界上。

    合法边界 = 一条普通的 user 消息：它既不是 tool_result（不会和前面的
    tool_use 拆散），也不会让历史以 assistant 开头。找不到就从头开始。
    """
    for index in range(min(desired, len(messages)), 0, -1):
        if _is_user(messages[index]) and not _carries_tool_result(messages[index]):
            return index
    return 0


def estimate_tokens(system: str, messages: list[Any]) -> int:
    total = len(system) + sum(len(str(message)) for message in messages)
    return total // CHARS_PER_TOKEN


def compose_system(base_prompt: str, business_context: str, summary: str | None) -> str:
    """SYSTEM + 业务事实 + 对话摘要。

    摘要放在业务事实之后，并明确它不是事实来源：两者冲突时以数据库为准。
    """
    blocks = [base_prompt, business_context]
    if summary:
        blocks.append(
            "[CONVERSATION_SUMMARY]\n"
            f"{summary}\n"
            "以上仅为早前对话的摘要，用于理解上下文。"
            "GPA、语言成绩、申请状态等事实一律以 [USER_PROFILE] 和 "
            "[CURRENT_APPLICATION_CONTEXT] 为准。\n"
            "[/CONVERSATION_SUMMARY]"
        )
    return "\n\n".join(blocks)


def plan_history(
    messages: list[Any], summarized_count: int, budget: ContextBudget
) -> tuple[int, int]:
    """决定这一轮要不要摘要、模型能看到哪一段。

    返回 (新的 summarized_count, 送进模型的起始下标)。
    两者相等表示不需要新的摘要。
    """
    pending = len(messages) - summarized_count
    if pending <= budget.summary_threshold:
        return summarized_count, safe_cut(messages, summarized_count)

    desired = max(summarized_count, len(messages) - budget.keep_recent)
    cut = safe_cut(messages, desired)
    if cut <= summarized_count:
        # 找不到更靠后的合法边界，这轮就先不摘要，下轮再看。
        return summarized_count, safe_cut(messages, summarized_count)
    return cut, cut
