import uuid
from datetime import date

from pydantic import BaseModel
from sqlmodel import Field, SQLModel

from app.harness import (
    PermissionLevel,
    ToolContext,
    ToolDefinition,
    ToolErrorCode,
    ToolExecutionError,
)
from app.modules.applications import service as application_service
from app.modules.applications.models import (
    Application,
    ApplicationStatus,
    ApplicationTask,
    TaskStatus,
    TaskType,
)
from app.modules.applications.schemas import (
    ApplicationCreate,
    ApplicationUpdate,
    TaskCreate,
    TaskUpdate,
)
from app.modules.programs import service as program_service


class ApplicationSummary(SQLModel):
    application_id: uuid.UUID
    program_id: uuid.UUID
    application_cycle: str
    status: ApplicationStatus
    target_deadline: date | None

    version: int


class TaskSummary(SQLModel):
    task_id: uuid.UUID
    task_type: TaskType
    title: str
    status: TaskStatus
    is_required: bool
    due_date: date | None
    version: int


class ReadinessSummary(SQLModel):
    is_ready: bool
    required_total: int
    required_done: int
    blocking_task_types: list[TaskType]


class CreateApplicationOutput(SQLModel):
    application: ApplicationSummary
    tasks: list[TaskSummary]
    readiness: ReadinessSummary


class CreateApplicationTaskInput(SQLModel):
    application_id: uuid.UUID
    task: TaskCreate


class CreateApplicationTaskOutput(SQLModel):
    task: TaskSummary


class UpdateApplicationTaskInput(SQLModel):
    task_id: uuid.UUID
    update: TaskUpdate


class UpdateApplicationTaskOutput(SQLModel):
    task: TaskSummary

    application: ApplicationSummary
    readiness: ReadinessSummary


def _application_summary(application: Application) -> ApplicationSummary:
    return ApplicationSummary(
        application_id=application.id,
        program_id=application.program_id,
        application_cycle=application.application_cycle,
        status=application.status,
        target_deadline=application.target_deadline,
        version=application.version,
    )


def _task_summary(task: ApplicationTask) -> TaskSummary:
    return TaskSummary(
        task_id=task.id,
        task_type=task.task_type,
        title=task.title,
        status=task.status,
        is_required=task.is_required,
        due_date=task.due_date,
        version=task.version,
    )


def _readiness_summary(
    readiness: application_service.Readiness,
) -> ReadinessSummary:
    return ReadinessSummary(
        is_ready=readiness.is_ready,
        required_total=readiness.required_total,
        required_done=readiness.required_done,
        blocking_task_types=[task.task_type for task in readiness.blocking_tasks],
    )


def create_application(ctx: ToolContext, payload: ApplicationCreate) -> BaseModel:
    try:
        application, tasks = application_service.create_application(
            session=ctx.session, user_id=ctx.user_id, application_in=payload
        )
    except application_service.ProgramNotFoundError as error:
        raise ToolExecutionError(ToolErrorCode.NOT_FOUND, str(error)) from error
    except application_service.ApplicationAlreadyExistsError as error:
        raise ToolExecutionError(
            ToolErrorCode.CONFLICT,
            str(error),
            {
                "existing_application_id": None
                if error.existing_id is None
                else str(error.existing_id)
            },
        ) from error

    return CreateApplicationOutput(
        application=_application_summary(application),
        tasks=[_task_summary(task) for task in tasks],
        readiness=_readiness_summary(application_service.evaluate_readiness(tasks)),
    )


def create_application_task(
    ctx: ToolContext, payload: CreateApplicationTaskInput
) -> BaseModel:
    try:
        task = application_service.create_task(
            session=ctx.session,
            user_id=ctx.user_id,
            application_id=payload.application_id,
            task_in=payload.task,
        )
    except application_service.ApplicationNotFoundError as error:
        raise ToolExecutionError(ToolErrorCode.NOT_FOUND, str(error)) from error
    return CreateApplicationTaskOutput(task=_task_summary(task))


def update_application_task(
    ctx: ToolContext, payload: UpdateApplicationTaskInput
) -> BaseModel:
    try:
        task, application = application_service.update_task(
            session=ctx.session,
            user_id=ctx.user_id,
            task_id=payload.task_id,
            task_in=payload.update,
        )
    except (
        application_service.TaskNotFoundError,
        application_service.ApplicationNotFoundError,
    ) as error:
        raise ToolExecutionError(ToolErrorCode.NOT_FOUND, str(error)) from error
    except (
        application_service.VersionConflictError,
        application_service.TaskTransitionError,
    ) as error:
        raise ToolExecutionError(ToolErrorCode.CONFLICT, str(error)) from error

    readiness = application_service.evaluate_readiness(
        application_service.list_tasks(
            session=ctx.session, application_id=application.id
        )
    )
    return UpdateApplicationTaskOutput(
        task=_task_summary(task),
        application=_application_summary(application),
        readiness=_readiness_summary(readiness),
    )


CREATE_APPLICATION = ToolDefinition(
    name="create_application",
    description=("把一个项目加入当前用户指定申请季的计划，并生成初始材料任务。"),
    input_model=ApplicationCreate,
    output_model=CreateApplicationOutput,
    permission_level=PermissionLevel.LOW_RISK_WRITE,
    handler=create_application,
)

CREATE_APPLICATION_TASK = ToolDefinition(
    name="create_application_task",
    description="为当前用户的申请新增一项材料或里程碑任务。",
    input_model=CreateApplicationTaskInput,
    output_model=CreateApplicationTaskOutput,
    permission_level=PermissionLevel.LOW_RISK_WRITE,
    handler=create_application_task,
)

UPDATE_APPLICATION_TASK = ToolDefinition(
    name="update_application_task",
    description=(
        "修改申请任务的状态、标题或截止日期。必须携带上次读取到的最新版本号。"
    ),
    input_model=UpdateApplicationTaskInput,
    output_model=UpdateApplicationTaskOutput,
    permission_level=PermissionLevel.LOW_RISK_WRITE,
    handler=update_application_task,
)


HIGH_RISK_TARGET_STATUSES = frozenset(
    {
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.OFFERED,
        ApplicationStatus.REJECTED,
    }
)


class UpdateApplicationStatusInput(SQLModel):
    application_id: uuid.UUID
    target_status: ApplicationStatus
    version: int = Field(ge=1)


class UpdateApplicationStatusOutput(SQLModel):
    application_id: uuid.UUID
    program_id: uuid.UUID
    program_name: str
    application_cycle: str
    previous_status: ApplicationStatus
    current_status: ApplicationStatus
    version: int
    readiness: ReadinessSummary


def escalate_application_status(payload: BaseModel) -> PermissionLevel:
    target = getattr(payload, "target_status", None)
    if target in HIGH_RISK_TARGET_STATUSES:
        return PermissionLevel.HIGH_RISK_WRITE
    return PermissionLevel.LOW_RISK_WRITE


def update_application_status(
    ctx: ToolContext, payload: UpdateApplicationStatusInput
) -> BaseModel:
    try:
        before = application_service.get_application(
            session=ctx.session,
            user_id=ctx.user_id,
            application_id=payload.application_id,
        )
    except application_service.ApplicationNotFoundError as error:
        raise ToolExecutionError(ToolErrorCode.NOT_FOUND, str(error)) from error

    previous_status = before.status
    program, _ = program_service.get_program_with_university(
        session=ctx.session, program_id=before.program_id
    )

    try:
        application = application_service.update_application(
            session=ctx.session,
            user_id=ctx.user_id,
            application_id=payload.application_id,
            application_in=ApplicationUpdate(
                version=payload.version,
                status=payload.target_status,
                confirm=True,
            ),
        )
    except application_service.ApplicationNotFoundError as error:
        raise ToolExecutionError(ToolErrorCode.NOT_FOUND, str(error)) from error
    except application_service.NotReadyError as error:
        raise ToolExecutionError(
            ToolErrorCode.DOMAIN_INVALID,
            str(error),
            {
                "blocking_task_types": [
                    task.task_type.value for task in error.readiness.blocking_tasks
                ],
                "required_done": error.readiness.required_done,
                "required_total": error.readiness.required_total,
            },
        ) from error
    except (
        application_service.TransitionError,
        application_service.VersionConflictError,
    ) as error:
        raise ToolExecutionError(ToolErrorCode.CONFLICT, str(error)) from error
    except application_service.ConfirmationRequiredError as error:
        raise ToolExecutionError(
            ToolErrorCode.INTERNAL,
            f"权限策略漏掉了业务层要求的确认：{error}",
        ) from error

    readiness = application_service.evaluate_readiness(
        application_service.list_tasks(
            session=ctx.session, application_id=application.id
        )
    )
    return UpdateApplicationStatusOutput(
        application_id=application.id,
        program_id=application.program_id,
        program_name=program.name,
        application_cycle=application.application_cycle,
        previous_status=previous_status,
        current_status=application.status,
        version=application.version,
        readiness=_readiness_summary(readiness),
    )


UPDATE_APPLICATION_STATUS = ToolDefinition(
    name="update_application_status",
    description=(
        "更新当前用户的一条申请状态，并携带上次读取到的版本号。只能按照状态机"
        "允许的路径流转；进入待提交前，所有必要任务必须完成。"
    ),
    input_model=UpdateApplicationStatusInput,
    output_model=UpdateApplicationStatusOutput,
    permission_level=PermissionLevel.LOW_RISK_WRITE,
    handler=update_application_status,
    escalate=escalate_application_status,
)
