"""对模型给出的引用做确定性核对。

全是普通 Python 比较，不用第二个模型去判断数字是否相等——
能用代码确定的事情就不该交给模型。

只核对模型自己声明的 citation：它引用的证据必须是本轮真读过的，
URL、数值和申请季都要对得上。
"""

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.agent.evidence import index

CITATION_PATTERN = re.compile(
    r"<citations>\s*(?P<body>\[.*?\])\s*</citations>", re.DOTALL
)

CITATION_INSTRUCTIONS = """\
陈述雅思、托福、GPA、截止日期、学费这类关键申请事实时，必须引用本轮工具
读到的证据，并在回答末尾附上一段机器可读的引用：

<citations>
[{"claim": "IELTS overall 7.0", "evidence_id": "…", "field_name": "ielts_overall",
  "value": "7.0", "application_cycle": "2026/27"}]
</citations>

evidence_id 只能原样抄自 [AVAILABLE_EVIDENCE] 或工具返回结果，绝不可自己编造；
value 必须与证据里的数值完全一致。没有证据支撑的关键事实就不要断言，
而是说明需要查证。没有关键事实时不要输出 citations 段。
"""

CONSERVATIVE_ANSWER = (
    "抱歉，我没有办法用已核实的官方证据支撑刚才要给你的关键信息，"
    "因此先不给出具体数值，避免误导。\n\n"
    "无法确认的是：{problems}\n\n"
    "建议我重新读取该项目的官方页面后再回答，或者你也可以直接查看学校官网。"
)


class Problem(StrEnum):
    UNKNOWN_EVIDENCE = "unknown_evidence"
    URL_MISMATCH = "url_mismatch"
    VALUE_MISMATCH = "value_mismatch"
    CYCLE_MISMATCH = "cycle_mismatch"
    MALFORMED = "malformed_citations"


@dataclass(frozen=True)
class Finding:
    problem: Problem
    detail: str


@dataclass
class Verdict:
    ok: bool
    findings: list[Finding] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return "；".join(finding.detail for finding in self.findings)


def split_answer(text: str | None) -> tuple[str, list[dict[str, Any]] | None, bool]:
    """拆出用户可见的正文和机器可读的引用。

    返回 (正文, 引用列表, 是否格式损坏)。没有 citations 段时引用为 None。
    """
    if not text:
        return "", None, False
    match = CITATION_PATTERN.search(text)
    if match is None:
        return text.strip(), None, False

    body = text[: match.start()] + text[match.end() :]
    try:
        parsed = json.loads(match.group("body"))
    except json.JSONDecodeError:
        return body.strip(), None, True
    if not isinstance(parsed, list) or not all(
        isinstance(item, dict) for item in parsed
    ):
        return body.strip(), None, True
    return body.strip(), parsed, False


def _same_value(left: Any, right: Any) -> bool:
    """数值按数值比，其余按去空白的字符串比。"""
    if left is None or right is None:
        return False
    left_text, right_text = str(left).strip(), str(right).strip()
    if left_text == right_text:
        return True
    try:
        return float(left_text) == float(right_text)
    except ValueError:
        return False


def verify(
    answer: str | None, evidence_records: list[dict[str, Any]]
) -> tuple[str, Verdict]:
    """核对一条最终回答。返回 (用户可见正文, 结论)。"""
    body, citations, malformed = split_answer(answer)

    if malformed:
        return body, Verdict(
            ok=False,
            findings=[Finding(Problem.MALFORMED, "引用段不是合法的 JSON 列表")],
        )
    if not citations:
        # 没有引用就没有可核对的断言；是否该有引用交给评测去衡量。
        return body, Verdict(ok=True)

    known = index(evidence_records)
    findings: list[Finding] = []

    for citation in citations:
        evidence_id = str(citation.get("evidence_id") or "")
        record = known.get(evidence_id)
        if record is None:
            findings.append(
                Finding(
                    Problem.UNKNOWN_EVIDENCE,
                    f"引用了本轮没有读到的证据 {evidence_id or '(空)'}",
                )
            )
            continue

        url = citation.get("source_url")
        if url and record.get("source_url") and url != record["source_url"]:
            findings.append(
                Finding(Problem.URL_MISMATCH, f"证据 {evidence_id} 的来源网址对不上")
            )

        value = citation.get("value")
        if value is not None and not _same_value(value, record.get("value")):
            findings.append(
                Finding(
                    Problem.VALUE_MISMATCH,
                    f"证据 {evidence_id} 的数值应为 {record.get('value')}，"
                    f"引用写的是 {value}",
                )
            )

        cycle = citation.get("application_cycle")
        if (
            cycle
            and record.get("application_cycle")
            and cycle != record["application_cycle"]
        ):
            findings.append(
                Finding(
                    Problem.CYCLE_MISMATCH,
                    f"证据 {evidence_id} 属于 {record['application_cycle']} 申请季，"
                    f"不能直接用于 {cycle}",
                )
            )

    return body, Verdict(ok=not findings, findings=findings, citations=citations)


def correction_request(verdict: Verdict) -> str:
    return (
        "你上一条回答的引用没有通过核对：\n"
        f"{verdict.summary}\n\n"
        "请只使用 [AVAILABLE_EVIDENCE] 中真实存在的 evidence_id，"
        "数值必须与证据完全一致。如果没有证据支撑，就明确说明无法确认，"
        "不要给出具体数值。"
    )


def conservative_answer(verdict: Verdict) -> str:
    return CONSERVATIVE_ANSWER.format(problems=verdict.summary or "关键事实缺少证据")
