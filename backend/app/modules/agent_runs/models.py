from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.agent.state import AgentStatus
from app.agent.trace import TraceEventType
from app.harness import PolicyOutcome, ToolErrorCode
from app.modules.columns import enum_column, get_datetime_utc

OPEN_STATUSES = (AgentStatus.RUNNING, AgentStatus.WAITING_CONFIRMATION)

_OPEN_SQL = ", ".join(f"'{status.value}'" for status in OPEN_STATUSES)


def _in_check(column: str, enum_type: type[StrEnum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in enum_type)
    return f"{column} IN ({values})"


def _nullable_in_check(column: str, enum_type: type[StrEnum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in enum_type)
    return f"{column} IS NULL OR {column} IN ({values})"


class AgentRun(SQLModel, table=True):
    __tablename__ = "agent_run"
    __table_args__ = (
        CheckConstraint(_in_check("status", AgentStatus), name="ck_agent_run_status"),
        CheckConstraint(
            _nullable_in_check("last_error_code", ToolErrorCode),
            name="ck_agent_run_last_error_code",
        ),
        CheckConstraint(
            f"(finished_at IS NULL) = (status IN ({_OPEN_SQL}))",
            name="ck_agent_run_finished_at",
        ),
        Index("ix_agent_run_user_started", "user_id", "started_at"),
    )

    id: uuid.UUID = Field(primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", ondelete="CASCADE", nullable=False
    )
    status: AgentStatus = Field(sa_column=enum_column(AgentStatus, length=32))
    started_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    finished_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    step_count: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    tool_call_count: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    final_answer: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    conversation_id: str | None = Field(default=None, max_length=96, index=True)
    user_message: str | None = Field(
        default=None,
        sa_column=Column("display_question", Text, nullable=True),
    )
    response_payload: dict | None = Field(
        default=None,
        sa_column=Column("display_response", JSON, nullable=True),
    )
    last_error_code: ToolErrorCode | None = Field(
        default=None, sa_column=enum_column(ToolErrorCode, length=32, nullable=True)
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AgentRunEvent(SQLModel, table=True):
    __tablename__ = "agent_run_event"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_agent_run_event_sequence"),
        CheckConstraint(
            _in_check("event_type", TraceEventType),
            name="ck_agent_run_event_type",
        ),
        CheckConstraint(
            _nullable_in_check("policy_outcome", PolicyOutcome),
            name="ck_agent_run_event_policy_outcome",
        ),
        CheckConstraint(
            _nullable_in_check("error_code", ToolErrorCode),
            name="ck_agent_run_event_error_code",
        ),
        CheckConstraint(
            "tool_result_status IS NULL OR tool_result_status IN ('ok', 'error')",
            name="ck_agent_run_event_result_status",
        ),
        CheckConstraint(
            _nullable_in_check("final_status", AgentStatus),
            name="ck_agent_run_event_final_status",
        ),
        CheckConstraint("sequence >= 0", name="ck_agent_run_event_sequence"),
        Index("ix_agent_run_event_run_sequence", "run_id", "sequence"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(
        foreign_key="agent_run.id", ondelete="CASCADE", nullable=False
    )
    sequence: int = Field(sa_column=Column(Integer, nullable=False))
    step: int = Field(sa_column=Column(Integer, nullable=False))
    event_type: TraceEventType = Field(sa_column=enum_column(TraceEventType, length=40))
    stop_reason: str | None = Field(default=None, max_length=32)
    produced_tool_calls: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    tool_name: str | None = Field(default=None, max_length=64)
    tool_call_id: str | None = Field(default=None, max_length=128)
    policy_outcome: PolicyOutcome | None = Field(
        default=None, sa_column=enum_column(PolicyOutcome, length=32, nullable=True)
    )
    tool_result_status: str | None = Field(default=None, max_length=8)
    error_code: ToolErrorCode | None = Field(
        default=None, sa_column=enum_column(ToolErrorCode, length=32, nullable=True)
    )
    latency_ms: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    final_status: str | None = Field(default=None, max_length=32)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
