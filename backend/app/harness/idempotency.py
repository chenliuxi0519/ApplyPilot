"""写工具的重放保护。

LangGraph 崩溃恢复时会重放尚未完成的节点。如果某个写工具已经落库、结果
却还没写回 checkpoint，重放就会把同一次写操作再执行一遍——用户会看到两条
重复的申请。人工确认流程把这个窗口拉得更长：确认可能隔几分钟才到，中间
任何一次重启都会走到重放。

做法是给每次工具调用一个稳定的键（run_id + call_id，重放时不变），执行前
先抢占一行：

* 抢到 -> 第一次执行，跑完把结果存下来；
* 撞上 succeeded 的旧行 -> 这次是重放，直接把上次的结果原样返回，不再碰业务表；
* 撞上 in_progress 的旧行 -> 上一次执行到一半就没了下文，副作用发生与否
  无法判断。这里**不重试**，直接报冲突让人来看：宁可多问一次，也不能悄悄
  写出第二条记录。

只保护写工具。只读工具重放没有副作用，不值得为它写一行记录。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, Session, SQLModel, col, select

__all__ = [
    "ClaimOutcome",
    "ToolExecution",
    "ToolExecutionStatus",
    "build_key",
    "claim",
    "complete",
    "release",
]


def _now() -> datetime:
    return datetime.now(UTC)


class ToolExecutionStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"


class ToolExecution(SQLModel, table=True):
    """一次写工具调用的执行记录，按 idempotency_key 唯一。"""

    __tablename__ = "tool_execution"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_tool_execution_key"),
        CheckConstraint(
            "status IN ('in_progress', 'succeeded')",
            name="ck_tool_execution_status",
        ),
        Index("ix_tool_execution_user_created", "user_id", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", ondelete="CASCADE", nullable=False
    )
    idempotency_key: str = Field(sa_column=Column(String(128), nullable=False))
    tool_name: str = Field(sa_column=Column(String(64), nullable=False))
    status: ToolExecutionStatus = Field(
        default=ToolExecutionStatus.IN_PROGRESS,
        sa_column=Column(String(16), nullable=False),
    )
    # 成功时存工具输出的 JSON，重放时原样返回，不重新执行 handler。
    output: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    created_at: datetime = Field(
        default_factory=_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


def build_key(*, run_id: str, call_id: str) -> str:
    """重放时必须得到同一个键：两者都来自 checkpoint 里的 state。"""
    return f"{run_id}:{call_id}"


@dataclass(frozen=True)
class ClaimOutcome:
    kind: Literal["fresh", "replay", "ambiguous"]
    output: dict[str, Any] | None = None


def _existing(session: Session, key: str) -> ToolExecution | None:
    return session.exec(
        select(ToolExecution).where(col(ToolExecution.idempotency_key) == key)
    ).one_or_none()


def claim(
    *, session: Session, user_id: uuid.UUID, key: str, tool_name: str
) -> ClaimOutcome:
    """抢占执行权，顺便回答"这次到底是不是重放"。

    先查一次是为了走常见路径；真正的并发安全靠 idempotency_key 上的唯一
    约束——两个 worker 同时插入，只有一个能成功，另一个转成重放分支。
    """
    found = _existing(session, key)
    if found is None:
        row = ToolExecution(user_id=user_id, idempotency_key=key, tool_name=tool_name)
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            # 并发下被别人抢先了，退回去按已存在处理。
            session.rollback()
            found = _existing(session, key)
        else:
            return ClaimOutcome(kind="fresh")

    if found is None:  # pragma: no cover - 唯一约束保证不会走到
        return ClaimOutcome(kind="fresh")
    if found.status == ToolExecutionStatus.SUCCEEDED:
        return ClaimOutcome(kind="replay", output=found.output)
    return ClaimOutcome(kind="ambiguous")


def complete(*, session: Session, key: str, output: dict[str, Any] | None) -> None:
    row = _existing(session, key)
    if row is None:  # pragma: no cover - claim 刚写过
        return
    row.status = ToolExecutionStatus.SUCCEEDED
    row.output = output
    row.completed_at = _now()
    session.add(row)
    session.commit()


def release(*, session: Session, key: str) -> None:
    """工具报错时放掉占位。

    工具返回错误说明业务表没有被改动，这次调用不需要被记住；留着反而会让
    后续重试撞上 in_progress 而被误判成"状态不明"。
    """
    row = _existing(session, key)
    if row is None:  # pragma: no cover
        return
    session.delete(row)
    session.commit()
