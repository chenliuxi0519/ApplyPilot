"""从工具结果里收集"本轮真正读到过的证据"。

只留引用需要的几个字段，不复制网页正文。
纯函数，按工具输出的形状取值，不认识领域模块。
"""

from typing import Any

# 会产出证据的工具，以及它们输出里证据列表的位置。
EVIDENCE_TOOLS = ("get_program_requirements", "research_program_requirements")


def extract(tool_name: str, output: dict[str, Any] | None) -> list[dict[str, Any]]:
    """把一次工具调用读到的证据摊平成记录。

    没有 evidence_id 的要求说明它没有已发布来源，不收进来——
    模型也就无法把它当作有出处的事实引用。
    """
    if tool_name not in EVIDENCE_TOOLS or not output:
        return []

    records: list[dict[str, Any]] = []
    for row in output.get("data") or []:
        evidence_id = row.get("evidence_id")
        if not evidence_id:
            continue
        records.append(
            {
                "evidence_id": str(evidence_id),
                "field_name": row.get("field_name"),
                "value": row.get("value"),
                "application_cycle": row.get("application_cycle"),
                "source_url": row.get("source_url"),
                "status": row.get("status"),
            }
        )
    return records


def index(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {record["evidence_id"]: record for record in records}


def render(records: list[dict[str, Any]]) -> str:
    """给模型看的可引用清单。只有这里出现过的 evidence_id 才允许引用。"""
    if not records:
        return ""
    lines = [
        f"- evidence_id={record['evidence_id']}"
        f" field={record['field_name']}"
        f" value={record['value']}"
        f" cycle={record['application_cycle']}"
        f" status={record['status']}"
        for record in index(records).values()
    ]
    body = "\n".join(lines)
    return f"[AVAILABLE_EVIDENCE]\n{body}\n[/AVAILABLE_EVIDENCE]"
