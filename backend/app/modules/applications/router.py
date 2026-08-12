import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.modules.applications import service
from app.modules.applications.models import Application, ApplicationStatus
from app.modules.applications.schemas import (
    ApplicationCreate,
    ApplicationDetailPublic,
    ApplicationPublic,
    ApplicationsPublic,
    ApplicationUpdate,
    BlockingTaskPublic,
    ReadinessPublic,
    TaskCreate,
    TaskPublic,
    TasksPublic,
    TaskUpdate,
)

router = APIRouter(
    prefix="/applications",
    tags=["applications"],
    dependencies=[Depends(get_current_user)],
)
task_router = APIRouter(
    prefix="/application-tasks",
    tags=["application-tasks"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/", response_model=ApplicationsPublic)
def list_applications(
    session: SessionDep,
    current_user: CurrentUser,
    status: ApplicationStatus | None = None,
    application_cycle: str | None = None,
    program_id: uuid.UUID | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    rows, count = service.list_applications(
        session=session,
        user_id=current_user.id,
        status=status,
        application_cycle=application_cycle,
        program_id=program_id,
        skip=skip,
        limit=limit,
    )
    return ApplicationsPublic(
        data=[ApplicationPublic.model_validate(row) for row in rows], count=count
    )


@router.post("/", response_model=ApplicationDetailPublic)
def create_application(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    application_in: ApplicationCreate,
) -> Any:
    try:
        application, tasks = service.create_application(
            session=session, user_id=current_user.id, application_in=application_in
        )
    except service.ProgramNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except service.ApplicationAlreadyExistsError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(error),
                "existing_application_id": str(error.existing_id)
                if error.existing_id
                else None,
            },
        ) from error
    return _detail(application=application, tasks=tasks)


@router.get("/{application_id}", response_model=ApplicationDetailPublic)
def read_application(
    session: SessionDep, current_user: CurrentUser, application_id: uuid.UUID
) -> Any:
    application = _get(
        session=session, user_id=current_user.id, application_id=application_id
    )
    tasks = service.list_tasks(session=session, application_id=application.id)
    return _detail(application=application, tasks=tasks)


@router.patch("/{application_id}", response_model=ApplicationDetailPublic)
def update_application(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    application_id: uuid.UUID,
    application_in: ApplicationUpdate,
) -> Any:
    try:
        application = service.update_application(
            session=session,
            user_id=current_user.id,
            application_id=application_id,
            application_in=application_in,
        )
    except service.ApplicationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except service.ConfirmationRequiredError as error:
        raise HTTPException(
            status_code=409, detail=_confirmation_detail(error)
        ) from error
    except service.NotReadyError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(error),
                "readiness": _readiness(error.readiness).model_dump(mode="json"),
            },
        ) from error
    except (service.TransitionError, service.VersionConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    tasks = service.list_tasks(session=session, application_id=application.id)
    return _detail(application=application, tasks=tasks)


@router.delete("/{application_id}")
def delete_application(
    session: SessionDep,
    current_user: CurrentUser,
    application_id: uuid.UUID,
    version: int = Query(ge=1),
    confirm: bool = False,
) -> Any:
    try:
        service.delete_application(
            session=session,
            user_id=current_user.id,
            application_id=application_id,
            version=version,
            confirmed=confirm,
        )
    except service.ApplicationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except service.ConfirmationRequiredError as error:
        raise HTTPException(
            status_code=409, detail=_confirmation_detail(error)
        ) from error
    except service.VersionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"message": "申请已删除"}


@router.get("/{application_id}/tasks", response_model=TasksPublic)
def list_application_tasks(
    session: SessionDep, current_user: CurrentUser, application_id: uuid.UUID
) -> Any:
    application = _get(
        session=session, user_id=current_user.id, application_id=application_id
    )
    tasks = service.list_tasks(session=session, application_id=application.id)
    return TasksPublic(
        data=[TaskPublic.model_validate(task) for task in tasks], count=len(tasks)
    )


@router.post("/{application_id}/tasks", response_model=TaskPublic)
def create_application_task(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    application_id: uuid.UUID,
    task_in: TaskCreate,
) -> Any:
    try:
        task = service.create_task(
            session=session,
            user_id=current_user.id,
            application_id=application_id,
            task_in=task_in,
        )
    except service.ApplicationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return TaskPublic.model_validate(task)


@task_router.patch("/{task_id}", response_model=TaskPublic)
def update_application_task(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    task_in: TaskUpdate,
) -> Any:
    try:
        task, _ = service.update_task(
            session=session,
            user_id=current_user.id,
            task_id=task_id,
            task_in=task_in,
        )
    except (
        service.TaskNotFoundError,
        service.ApplicationNotFoundError,
    ) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (
        service.TaskTransitionError,
        service.VersionConflictError,
    ) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return TaskPublic.model_validate(task)


@task_router.delete("/{task_id}")
def delete_application_task(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    version: int = Query(ge=1),
) -> Any:
    try:
        service.delete_task(
            session=session,
            user_id=current_user.id,
            task_id=task_id,
            version=version,
        )
    except (
        service.TaskNotFoundError,
        service.ApplicationNotFoundError,
    ) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (
        service.TaskDeletionError,
        service.VersionConflictError,
    ) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"message": "任务已删除"}


def _get(
    *, session: Session, user_id: uuid.UUID, application_id: uuid.UUID
) -> Application:
    try:
        return service.get_application(
            session=session, user_id=user_id, application_id=application_id
        )
    except service.ApplicationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _confirmation_detail(
    error: service.ConfirmationRequiredError,
) -> dict[str, Any]:
    return {
        "message": str(error),
        "requires_confirmation": True,
        "action": error.action.value,
        "effects": error.effects,
    }


def _readiness(readiness: service.Readiness) -> ReadinessPublic:
    return ReadinessPublic(
        is_ready=readiness.is_ready,
        required_total=readiness.required_total,
        required_done=readiness.required_done,
        blocking_tasks=[
            BlockingTaskPublic.model_validate(task) for task in readiness.blocking_tasks
        ],
    )


def _detail(*, application: Application, tasks: list[Any]) -> ApplicationDetailPublic:
    readiness = service.evaluate_readiness(tasks)
    return ApplicationDetailPublic(
        **ApplicationPublic.model_validate(application).model_dump(),
        readiness=_readiness(readiness),
        tasks=[TaskPublic.model_validate(task) for task in tasks],
    )
