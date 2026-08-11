from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.modules.columns import enum_column, get_datetime_utc
from app.modules.programs.models import APPLICATION_CYCLE_PATTERN


class ApplicationStatus(StrEnum):
    SHORTLISTED = "shortlisted"
    PREPARING = "preparing"
    READY_TO_SUBMIT = "ready_to_submit"
    SUBMITTED = "submitted"
    RESULT_PENDING = "result_pending"
    OFFERED = "offered"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class TaskType(StrEnum):
    CV = "cv"
    PERSONAL_STATEMENT = "personal_statement"
    TRANSCRIPT = "transcript"
    LANGUAGE_SCORE = "language_score"
    RECOMMENDATION = "recommendation"
    APPLICATION_FORM = "application_form"
    OTHER = "other"


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"


class TaskSource(StrEnum):
    TEMPLATE = "template"
    PROGRAM_REQUIREMENT = "program_requirement"
    USER = "user"


def _in_check(column: str, enum_type: type[StrEnum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in enum_type)
    return f"{column} IN ({values})"


SUBMITTED_STATUSES = (
    ApplicationStatus.SUBMITTED,
    ApplicationStatus.RESULT_PENDING,
    ApplicationStatus.OFFERED,
    ApplicationStatus.REJECTED,
)

_SUBMITTED_SQL = ", ".join(f"'{status.value}'" for status in SUBMITTED_STATUSES)


APPLICATION_VERSION_COLUMN = Column("version", Integer, nullable=False)
TASK_VERSION_COLUMN = Column("version", Integer, nullable=False)


class Application(SQLModel, table=True):
    __tablename__ = "application"
    __mapper_args__ = {"version_id_col": APPLICATION_VERSION_COLUMN}
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "program_id",
            "application_cycle",
            name="uq_application_user_program_cycle",
        ),
        CheckConstraint(
            f"application_cycle ~ '{APPLICATION_CYCLE_PATTERN}'",
            name="ck_application_application_cycle",
        ),
        CheckConstraint(
            _in_check("status", ApplicationStatus), name="ck_application_status"
        ),
        CheckConstraint(
            f"status NOT IN ({_SUBMITTED_SQL}) OR submitted_at IS NOT NULL",
            name="ck_application_submitted_at",
        ),
        Index("ix_application_user_status", "user_id", "status"),
        Index("ix_application_user_deadline", "user_id", "target_deadline"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id",
        ondelete="CASCADE",
        nullable=False,
    )

    program_id: uuid.UUID = Field(
        foreign_key="program.id",
        ondelete="RESTRICT",
        nullable=False,
    )
    application_cycle: str = Field(max_length=7, nullable=False)
    status: ApplicationStatus = Field(
        default=ApplicationStatus.SHORTLISTED,
        sa_column=enum_column(ApplicationStatus, length=32),
    )
    target_deadline: date | None = Field(
        default=None, sa_column=Column(Date(), nullable=True)
    )
    submitted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    version: int = Field(default=1, sa_column=APPLICATION_VERSION_COLUMN)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ApplicationTask(SQLModel, table=True):
    __tablename__ = "application_task"
    __mapper_args__ = {"version_id_col": TASK_VERSION_COLUMN}
    __table_args__ = (
        CheckConstraint(
            _in_check("task_type", TaskType), name="ck_application_task_type"
        ),
        CheckConstraint(
            _in_check("status", TaskStatus), name="ck_application_task_status"
        ),
        CheckConstraint(
            _in_check("source", TaskSource), name="ck_application_task_source"
        ),
        CheckConstraint(
            "(status = 'done') = (completed_at IS NOT NULL)",
            name="ck_application_task_completed_at",
        ),
        Index("ix_application_task_application_status", "application_id", "status"),
        Index("ix_application_task_application_due", "application_id", "due_date"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    application_id: uuid.UUID = Field(
        foreign_key="application.id",
        ondelete="CASCADE",
        nullable=False,
    )
    task_type: TaskType = Field(sa_column=enum_column(TaskType, length=64))
    title: str = Field(max_length=255, nullable=False)
    status: TaskStatus = Field(
        default=TaskStatus.TODO, sa_column=enum_column(TaskStatus, length=32)
    )
    due_date: date | None = Field(default=None, sa_column=Column(Date(), nullable=True))
    is_required: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))
    source: TaskSource = Field(
        default=TaskSource.USER, sa_column=enum_column(TaskSource, length=32)
    )
    source_requirement_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="program_requirement.id",
        ondelete="SET NULL",
        nullable=True,
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    version: int = Field(default=1, sa_column=TASK_VERSION_COLUMN)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


__all__ = [
    "SUBMITTED_STATUSES",
    "Application",
    "ApplicationStatus",
    "ApplicationTask",
    "TaskSource",
    "TaskStatus",
    "TaskType",
]
