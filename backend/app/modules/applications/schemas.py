import uuid
from datetime import date, datetime

from pydantic import model_validator
from sqlmodel import Field, SQLModel

from app.modules.applications.models import (
    ApplicationStatus,
    TaskSource,
    TaskStatus,
    TaskType,
)
from app.modules.programs.schemas import ApplicationCycle


class ApplicationCreate(SQLModel):
    program_id: uuid.UUID
    application_cycle: ApplicationCycle
    target_deadline: date | None = None


class ApplicationUpdate(SQLModel):
    version: int = Field(ge=1)
    confirm: bool = False
    status: ApplicationStatus | None = None
    target_deadline: date | None = None

    @model_validator(mode="after")
    def validate_update(self) -> "ApplicationUpdate":
        changed = self.model_fields_set - {"version", "confirm"}
        if not changed:
            raise ValueError("状态和目标截止日期至少需要提供一项")
        return self


class TaskCreate(SQLModel):
    task_type: TaskType
    title: str = Field(min_length=1, max_length=255)
    due_date: date | None = None
    is_required: bool = False


class TaskUpdate(SQLModel):
    version: int = Field(ge=1)
    status: TaskStatus | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    due_date: date | None = None

    @model_validator(mode="after")
    def validate_update(self) -> "TaskUpdate":
        if not self.model_fields_set - {"version"}:
            raise ValueError("至少需要提供一个任务字段")

        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("任务标题不能为空")
        return self


class TaskPublic(SQLModel):
    id: uuid.UUID
    application_id: uuid.UUID
    task_type: TaskType
    title: str
    status: TaskStatus
    due_date: date | None
    is_required: bool
    source: TaskSource
    source_requirement_id: uuid.UUID | None
    completed_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class TasksPublic(SQLModel):
    data: list[TaskPublic]
    count: int


class BlockingTaskPublic(SQLModel):
    id: uuid.UUID
    task_type: TaskType
    title: str
    status: TaskStatus


class ReadinessPublic(SQLModel):
    is_ready: bool
    required_total: int
    required_done: int
    blocking_tasks: list[BlockingTaskPublic]


class ApplicationPublic(SQLModel):
    id: uuid.UUID
    user_id: uuid.UUID
    program_id: uuid.UUID
    application_cycle: str
    status: ApplicationStatus
    target_deadline: date | None
    submitted_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class ApplicationDetailPublic(ApplicationPublic):
    readiness: ReadinessPublic
    tasks: list[TaskPublic]


class ApplicationsPublic(SQLModel):
    data: list[ApplicationPublic]
    count: int


class ConfirmationRequiredPublic(SQLModel):
    detail: str
    requires_confirmation: bool
    action: str
    effects: list[str]
