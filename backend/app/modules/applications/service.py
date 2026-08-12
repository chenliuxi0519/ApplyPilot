import uuid
from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.modules.applications.models import (
    Application,
    ApplicationStatus,
    ApplicationTask,
    TaskSource,
    TaskStatus,
    TaskType,
)
from app.modules.applications.schemas import (
    ApplicationCreate,
    ApplicationUpdate,
    TaskCreate,
    TaskUpdate,
)
from app.modules.applications.state_machine import (
    BASE_TASK_TEMPLATE,
    LANGUAGE_REQUIREMENT_FIELDS,
    LANGUAGE_TASK_TITLE,
    LANGUAGE_TASK_TITLE_UNVERIFIED,
    HighRiskAction,
    effects_of,
    high_risk_action,
    is_submitted,
    is_task_reopen,
    is_transition_allowed,
)
from app.modules.columns import get_datetime_utc
from app.modules.programs.models import (
    EvidenceStatus,
    Program,
    ProgramRequirement,
    RequirementEvidence,
    RequirementFieldName,
    RequirementStatus,
)


class ApplicationNotFoundError(LookupError):
    pass


class TaskNotFoundError(LookupError):
    pass


class ProgramNotFoundError(LookupError):
    pass


class ApplicationAlreadyExistsError(ValueError):
    def __init__(self, message: str, existing_id: uuid.UUID | None = None) -> None:
        super().__init__(message)
        self.existing_id = existing_id


class VersionConflictError(ValueError):
    pass


class TransitionError(ValueError):
    pass


class TaskTransitionError(ValueError):
    pass


class TaskDeletionError(ValueError):
    pass


class NotReadyError(ValueError):
    def __init__(self, message: str, readiness: "Readiness") -> None:
        super().__init__(message)
        self.readiness = readiness


class ConfirmationRequiredError(Exception):
    def __init__(self, action: HighRiskAction) -> None:
        super().__init__(f"{action.value} requires confirmation")
        self.action = action
        self.effects = effects_of(action)


@dataclass
class Readiness:
    is_ready: bool
    required_total: int
    required_done: int
    blocking_tasks: list[ApplicationTask] = field(default_factory=list)


def evaluate_readiness(tasks: list[ApplicationTask]) -> Readiness:
    required = [task for task in tasks if task.is_required]
    blocking = [task for task in required if task.status is not TaskStatus.DONE]
    return Readiness(
        is_ready=bool(required) and not blocking,
        required_total=len(required),
        required_done=len(required) - len(blocking),
        blocking_tasks=blocking,
    )


def list_applications(
    *,
    session: Session,
    user_id: uuid.UUID,
    status: ApplicationStatus | None = None,
    application_cycle: str | None = None,
    program_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Application], int]:
    conditions: list[ColumnElement[bool]] = [col(Application.user_id) == user_id]
    if status is not None:
        conditions.append(col(Application.status) == status)
    if application_cycle is not None:
        conditions.append(col(Application.application_cycle) == application_cycle)
    if program_id is not None:
        conditions.append(col(Application.program_id) == program_id)

    count_statement = select(func.count()).select_from(Application)
    statement = select(Application)
    for condition in conditions:
        count_statement = count_statement.where(condition)
        statement = statement.where(condition)

    count = session.exec(count_statement).one()
    rows = list(
        session.exec(
            statement.order_by(
                col(Application.target_deadline).asc().nullslast(),
                col(Application.created_at).desc(),
            )
            .offset(skip)
            .limit(limit)
        ).all()
    )
    return rows, count


def get_application(
    *, session: Session, user_id: uuid.UUID, application_id: uuid.UUID
) -> Application:
    statement = (
        select(Application)
        .where(col(Application.id) == application_id)
        .where(col(Application.user_id) == user_id)
    )
    application = session.exec(statement).one_or_none()
    if application is None:
        raise ApplicationNotFoundError("申请不存在")
    return application


def list_tasks(*, session: Session, application_id: uuid.UUID) -> list[ApplicationTask]:
    statement = (
        select(ApplicationTask)
        .where(col(ApplicationTask.application_id) == application_id)
        .order_by(
            col(ApplicationTask.is_required).desc(),
            col(ApplicationTask.task_type),
        )
    )
    return list(session.exec(statement).all())


def create_application(
    *, session: Session, user_id: uuid.UUID, application_in: ApplicationCreate
) -> tuple[Application, list[ApplicationTask]]:
    try:
        program = session.get(Program, application_in.program_id)
        if program is None:
            raise ProgramNotFoundError("项目不存在")

        verified = _verified_requirements(
            session=session,
            program_id=application_in.program_id,
            application_cycle=application_in.application_cycle,
        )

        target_deadline = application_in.target_deadline
        if target_deadline is None:
            deadline_requirement = verified.get(
                RequirementFieldName.APPLICATION_DEADLINE
            )
            if deadline_requirement is not None:
                target_deadline = deadline_requirement.date_value

        application = Application(
            user_id=user_id,
            program_id=application_in.program_id,
            application_cycle=application_in.application_cycle,
            status=ApplicationStatus.SHORTLISTED,
            target_deadline=target_deadline,
        )
        session.add(application)
        session.flush()

        tasks = _generate_initial_tasks(
            session=session, application=application, verified=verified
        )

        session.commit()
        session.refresh(application)
        for task in tasks:
            session.refresh(task)
        return application, tasks
    except IntegrityError as error:
        session.rollback()
        existing = session.exec(
            select(Application)
            .where(col(Application.user_id) == user_id)
            .where(col(Application.program_id) == application_in.program_id)
            .where(
                col(Application.application_cycle) == application_in.application_cycle
            )
        ).one_or_none()
        raise ApplicationAlreadyExistsError(
            "该项目在当前申请季已加入申请计划",
            None if existing is None else existing.id,
        ) from error
    except Exception:
        session.rollback()
        raise


def update_application(
    *,
    session: Session,
    user_id: uuid.UUID,
    application_id: uuid.UUID,
    application_in: ApplicationUpdate,
) -> Application:
    try:
        application = _lock_application(
            session=session, user_id=user_id, application_id=application_id
        )
        _check_version(expected=application_in.version, actual=application.version)

        changed = False
        fields_set = application_in.model_fields_set

        if "target_deadline" in fields_set:
            if application_in.target_deadline != application.target_deadline:
                application.target_deadline = application_in.target_deadline
                changed = True

        if application_in.status is not None:
            _apply_transition(
                session=session,
                application=application,
                target=application_in.status,
                confirmed=application_in.confirm,
            )
            changed = True

        if changed:
            application.updated_at = get_datetime_utc()
            session.add(application)

        session.commit()
        session.refresh(application)
        return application
    except Exception:
        session.rollback()
        raise


def delete_application(
    *,
    session: Session,
    user_id: uuid.UUID,
    application_id: uuid.UUID,
    version: int,
    confirmed: bool,
) -> None:
    try:
        application = _lock_application(
            session=session, user_id=user_id, application_id=application_id
        )
        _check_version(expected=version, actual=application.version)
        if not confirmed:
            raise ConfirmationRequiredError(HighRiskAction.DELETE_APPLICATION)

        session.delete(application)
        session.commit()
    except Exception:
        session.rollback()
        raise


def create_task(
    *,
    session: Session,
    user_id: uuid.UUID,
    application_id: uuid.UUID,
    task_in: TaskCreate,
) -> ApplicationTask:
    try:
        application = _lock_application(
            session=session, user_id=user_id, application_id=application_id
        )
        task = ApplicationTask(
            application_id=application.id,
            task_type=task_in.task_type,
            title=task_in.title,
            due_date=task_in.due_date,
            is_required=task_in.is_required,
            source=TaskSource.USER,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        return task
    except Exception:
        session.rollback()
        raise


def update_task(
    *,
    session: Session,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    task_in: TaskUpdate,
) -> tuple[ApplicationTask, Application]:
    try:
        task = session.get(ApplicationTask, task_id)
        if task is None:
            raise TaskNotFoundError("任务不存在")

        application = _lock_application(
            session=session, user_id=user_id, application_id=task.application_id
        )
        session.refresh(task)
        _check_version(expected=task_in.version, actual=task.version)

        now = get_datetime_utc()
        changed = False
        fields_set = task_in.model_fields_set

        if task_in.title is not None and task_in.title != task.title:
            task.title = task_in.title
            changed = True
        if "due_date" in fields_set and task_in.due_date != task.due_date:
            task.due_date = task_in.due_date
            changed = True

        if task_in.status is not None and task_in.status is not task.status:
            if (
                is_submitted(application.status)
                and task.is_required
                and is_task_reopen(task.status, task_in.status)
            ):
                raise TaskTransitionError("申请提交后不能重新打开必要任务")
            task.status = task_in.status
            task.completed_at = now if task_in.status is TaskStatus.DONE else None
            changed = True

        if changed:
            task.updated_at = now
            session.add(task)
            session.flush()
            _demote_if_no_longer_ready(session=session, application=application)

        session.commit()
        session.refresh(task)
        session.refresh(application)
        return task, application
    except Exception:
        session.rollback()
        raise


def delete_task(
    *,
    session: Session,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    version: int,
) -> None:
    try:
        task = session.get(ApplicationTask, task_id)
        if task is None:
            raise TaskNotFoundError("任务不存在")
        application = _lock_application(
            session=session,
            user_id=user_id,
            application_id=task.application_id,
        )
        session.refresh(task)
        _check_version(expected=version, actual=task.version)
        if task.source is not TaskSource.USER:
            raise TaskDeletionError("只能删除用户自己创建的任务")
        session.delete(task)
        session.flush()
        _demote_if_no_longer_ready(session=session, application=application)
        session.commit()
    except Exception:
        session.rollback()
        raise


def _demote_if_no_longer_ready(*, session: Session, application: Application) -> None:
    if application.status is not ApplicationStatus.READY_TO_SUBMIT:
        return
    readiness = evaluate_readiness(
        list_tasks(session=session, application_id=application.id)
    )
    if not readiness.is_ready:
        application.status = ApplicationStatus.PREPARING
        application.updated_at = get_datetime_utc()
        session.add(application)


def _apply_transition(
    *,
    session: Session,
    application: Application,
    target: ApplicationStatus,
    confirmed: bool,
) -> None:
    current = application.status
    if target is current:
        raise TransitionError(f"Application is already {current.value}")
    if not is_transition_allowed(current, target):
        raise TransitionError(
            f"Cannot move an application from {current.value} to {target.value}"
        )

    action = high_risk_action(target)
    if action is not None and not confirmed:
        raise ConfirmationRequiredError(action)

    if target is ApplicationStatus.READY_TO_SUBMIT:
        readiness = evaluate_readiness(
            list_tasks(session=session, application_id=application.id)
        )
        if not readiness.is_ready:
            raise NotReadyError("所有必要任务完成后才能进入待提交状态", readiness)

    if target is ApplicationStatus.SUBMITTED:
        application.submitted_at = get_datetime_utc()

    application.status = target


def _lock_application(
    *, session: Session, user_id: uuid.UUID, application_id: uuid.UUID
) -> Application:
    statement = (
        select(Application)
        .where(col(Application.id) == application_id)
        .where(col(Application.user_id) == user_id)
        .with_for_update()
    )
    application = session.exec(statement).one_or_none()
    if application is None:
        raise ApplicationNotFoundError("申请不存在")
    return application


def _check_version(*, expected: int, actual: int) -> None:
    if expected != actual:
        raise VersionConflictError(
            f"Record was modified by someone else; expected version {actual}"
        )


def _verified_requirements(
    *, session: Session, program_id: uuid.UUID, application_cycle: str
) -> dict[RequirementFieldName, ProgramRequirement]:
    statement = (
        select(ProgramRequirement)
        .join(
            RequirementEvidence,
            col(ProgramRequirement.published_evidence_id)
            == col(RequirementEvidence.id),
        )
        .where(col(ProgramRequirement.program_id) == program_id)
        .where(col(ProgramRequirement.application_cycle) == application_cycle)
        .where(col(ProgramRequirement.status) == RequirementStatus.PUBLISHED)
        .where(col(RequirementEvidence.status) == EvidenceStatus.VERIFIED)
    )
    return {row.field_name: row for row in session.exec(statement).all()}


def _generate_initial_tasks(
    *,
    session: Session,
    application: Application,
    verified: dict[RequirementFieldName, ProgramRequirement],
) -> list[ApplicationTask]:
    due_date = application.target_deadline
    tasks = [
        ApplicationTask(
            application_id=application.id,
            task_type=entry.task_type,
            title=entry.title,
            is_required=entry.is_required,
            source=entry.source,
            due_date=due_date,
        )
        for entry in BASE_TASK_TEMPLATE
    ]

    language_requirement = next(
        (
            verified[field_name]
            for field_name in LANGUAGE_REQUIREMENT_FIELDS
            if field_name in verified
        ),
        None,
    )
    if language_requirement is None:
        tasks.append(
            ApplicationTask(
                application_id=application.id,
                task_type=TaskType.LANGUAGE_SCORE,
                title=LANGUAGE_TASK_TITLE_UNVERIFIED,
                is_required=False,
                source=TaskSource.TEMPLATE,
                due_date=due_date,
            )
        )
    else:
        tasks.append(
            ApplicationTask(
                application_id=application.id,
                task_type=TaskType.LANGUAGE_SCORE,
                title=LANGUAGE_TASK_TITLE,
                is_required=True,
                source=TaskSource.PROGRAM_REQUIREMENT,
                source_requirement_id=language_requirement.id,
                due_date=due_date,
            )
        )

    session.add_all(tasks)
    return tasks
