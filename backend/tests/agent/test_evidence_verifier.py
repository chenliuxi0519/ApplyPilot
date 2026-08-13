"""Evidence Verifier 的确定性核对。

全部是代码比较，没有第二个模型参与判断。
"""

import uuid
from typing import Any

import pytest
from sqlmodel import Session

from app.agent.evidence import extract, render
from app.agent.graph import build_graph, new_state
from app.agent.recorder import InMemoryRunRecorder
from app.agent.verifier import (
    Problem,
    conservative_answer,
    split_answer,
    verify,
)
from app.core.config import settings
from tests.agent.test_context import RecordingModel
from tests.agent.test_graph import _answer, _call, _config, _context, _uses
from tests.utils.program import (
    create_random_program,
    create_random_university,
    ielts_evidence,
)
from tests.utils.user import create_random_user

TEST_KEY = "applypilot-test-key-32-bytes!!!!"

EVIDENCE = [
    {
        "evidence_id": "ev-1",
        "field_name": "ielts_overall",
        "value": "7.0",
        "application_cycle": "2026/27",
        "source_url": "https://nus.edu.sg/admissions",
        "status": "published",
    }
]


@pytest.fixture(autouse=True)
def encryption_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHECKPOINT_ENCRYPTION_KEY", TEST_KEY)


def _cite(**overrides: Any) -> str:
    citation = {
        "claim": "IELTS overall 7.0",
        "evidence_id": "ev-1",
        "field_name": "ielts_overall",
        "value": "7.0",
        "application_cycle": "2026/27",
    }
    citation.update(overrides)
    import json

    return f"雅思要求是 7.0。<citations>{json.dumps([citation])}</citations>"


# --------------------------------------------------------------------------
# 拆分与收集
# --------------------------------------------------------------------------


def test_the_citation_block_is_stripped_from_the_visible_answer() -> None:
    body, citations, malformed = split_answer(_cite())

    assert body == "雅思要求是 7.0。"
    assert malformed is False
    assert citations is not None and citations[0]["evidence_id"] == "ev-1"


def test_an_answer_without_citations_is_left_alone() -> None:
    body, citations, malformed = split_answer("你好，我可以帮你规划申请。")

    assert body == "你好，我可以帮你规划申请。"
    assert citations is None and malformed is False


def test_a_broken_citation_block_is_reported() -> None:
    _, _, malformed = split_answer("答案 <citations>[不是 JSON]</citations>")

    assert malformed is True


def test_only_requirements_with_published_evidence_are_collectable() -> None:
    output = {
        "data": [
            {
                "evidence_id": "ev-1",
                "field_name": "ielts_overall",
                "value": "7.0",
                "application_cycle": "2026/27",
                "source_url": "https://x",
                "status": "published",
            },
            {  # 没有已发布证据，不可引用
                "evidence_id": None,
                "field_name": "gpa_min",
                "value": "3.5",
                "application_cycle": "2026/27",
                "status": "conflict_pending",
            },
        ]
    }

    records = extract("get_program_requirements", output)

    assert [record["evidence_id"] for record in records] == ["ev-1"]


def test_a_tool_that_produces_no_evidence_contributes_nothing() -> None:
    assert extract("search_programs", {"data": [{"program_id": "p"}]}) == []
    assert extract("get_program_requirements", None) == []


def test_the_rendered_block_lists_only_known_evidence() -> None:
    block = render(EVIDENCE)

    assert "[AVAILABLE_EVIDENCE]" in block
    assert "evidence_id=ev-1" in block
    assert render([]) == ""


# --------------------------------------------------------------------------
# 四项确定性检查
# --------------------------------------------------------------------------


def test_a_faithful_citation_passes() -> None:
    _, verdict = verify(_cite(), EVIDENCE)

    assert verdict.ok is True


def test_an_invented_evidence_id_is_rejected() -> None:
    _, verdict = verify(_cite(evidence_id="ev-does-not-exist"), EVIDENCE)

    assert verdict.ok is False
    assert verdict.findings[0].problem is Problem.UNKNOWN_EVIDENCE


def test_citing_evidence_that_was_never_read_is_rejected() -> None:
    _, verdict = verify(_cite(), [])

    assert verdict.ok is False
    assert verdict.findings[0].problem is Problem.UNKNOWN_EVIDENCE


def test_a_mismatched_url_is_rejected() -> None:
    _, verdict = verify(_cite(source_url="https://evil.example.com/fake"), EVIDENCE)

    assert verdict.ok is False
    assert verdict.findings[0].problem is Problem.URL_MISMATCH


def test_a_changed_number_is_rejected() -> None:
    _, verdict = verify(_cite(value="6.5"), EVIDENCE)

    assert verdict.ok is False
    assert verdict.findings[0].problem is Problem.VALUE_MISMATCH


def test_the_same_number_written_differently_still_passes() -> None:
    """7.00 和 7.0 是同一个数，不该判成不一致。"""
    _, verdict = verify(_cite(value="7.00"), EVIDENCE)

    assert verdict.ok is True


def test_borrowing_evidence_from_another_cycle_is_rejected() -> None:
    _, verdict = verify(_cite(application_cycle="2027/28"), EVIDENCE)

    assert verdict.ok is False
    assert verdict.findings[0].problem is Problem.CYCLE_MISMATCH


def test_every_problem_is_reported_not_just_the_first() -> None:
    _, verdict = verify(_cite(value="6.0", application_cycle="2027/28"), EVIDENCE)

    problems = {finding.problem for finding in verdict.findings}
    assert problems == {Problem.VALUE_MISMATCH, Problem.CYCLE_MISMATCH}


def test_the_conservative_answer_names_the_problem() -> None:
    _, verdict = verify(_cite(evidence_id="nope"), EVIDENCE)
    text = conservative_answer(verdict)

    assert "无法确认" in text or "没有办法" in text
    assert "nope" in text


# --------------------------------------------------------------------------
# 接进图里：编造引用会被拦下并降级
# --------------------------------------------------------------------------


def _evidence_program(db: Session) -> Any:
    university = create_random_university(db)
    return create_random_program(db, university=university)


def test_a_fabricated_citation_is_downgraded_to_a_conservative_answer(
    db: Session, checkpointer: Any
) -> None:
    user = create_random_user(db)
    # 两次都编造 evidence_id：第一次触发重写，第二次仍失败 -> 保守回答
    model = RecordingModel(
        [
            _answer(
                '雅思要求 7.0。<citations>[{"evidence_id": "made-up", "value": "7.0"}]</citations>'
            ),
            _answer(
                '还是 7.0。<citations>[{"evidence_id": "made-up-again", "value": "7.0"}]</citations>'
            ),
        ]
    )
    context = _context(db, user, model, InMemoryRunRecorder())

    result = build_graph(checkpointer).invoke(
        new_state(uuid.uuid4(), "NUS 的雅思要求是多少？", model),
        config=_config(user.id, f"c-{uuid.uuid4().hex}"),
        context=context,
    )

    assert "没有办法用已核实的官方证据" in result["final_answer"]
    assert "7.0" not in result["final_answer"]


def test_a_correct_citation_survives_and_loses_only_the_markup(
    db: Session, checkpointer: Any
) -> None:
    user = create_random_user(db)
    program = _evidence_program(db)
    model = RecordingModel(
        [
            _uses(_call("get_program_requirements", {"program_id": str(program.id)})),
            _answer("我先看看要求。"),
        ]
    )
    context = _context(db, user, model, InMemoryRunRecorder())

    result = build_graph(checkpointer).invoke(
        new_state(uuid.uuid4(), "这个项目要求什么？", model),
        config=_config(user.id, f"c-{uuid.uuid4().hex}"),
        context=context,
    )

    assert result["final_answer"] == "我先看看要求。"
    # 读过要求之后，可引用证据进入 state
    assert isinstance(result["evidence"], list)


def test_evidence_read_in_this_run_becomes_citable(
    db: Session, checkpointer: Any
) -> None:
    """真读过的证据要出现在 state 里，并被渲染进下一轮 system。"""
    from app.modules.programs.service import ingest_evidence

    user = create_random_user(db)
    program = _evidence_program(db)
    ingested = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.0")
    )
    evidence = ingested.evidence

    model = RecordingModel(
        [
            _uses(_call("get_program_requirements", {"program_id": str(program.id)})),
            _answer("这个项目的要求如上。"),
        ]
    )
    context = _context(db, user, model, InMemoryRunRecorder())
    result = build_graph(checkpointer).invoke(
        new_state(uuid.uuid4(), "要求是什么？", model),
        config=_config(user.id, f"c-{uuid.uuid4().hex}"),
        context=context,
    )

    ids = {record["evidence_id"] for record in result["evidence"]}
    assert str(evidence.id) in ids
    # 第二次模型调用的 system 里带上了可引用清单
    assert "[AVAILABLE_EVIDENCE]" in model.systems[1]
    assert str(evidence.id) in model.systems[1]


@pytest.fixture
def checkpointer() -> Any:
    from app.agent.checkpointer import open_checkpointer

    with open_checkpointer() as saver:
        saver.setup()
        yield saver
