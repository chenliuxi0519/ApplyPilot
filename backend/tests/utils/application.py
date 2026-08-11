import uuid

from sqlmodel import Session

from app.models import User
from app.modules.applications.models import (
    Application,
    ApplicationStatus,
    ApplicationTask,
    TaskStatus,
)
from app.modules.applications.schemas import (
    ApplicationCreate,
    ApplicationUpdate,
    TaskUpdate,
)
from app.modules.applications.service import (
    create_application,
    list_tasks,
    update_application,
    update_task,
)
from tests.utils.program import APPLICATION_CYCLE, create_random_program
from tests.utils.user import create_random_user


def create_application_for(
    db: Session,
    *,
    user: User | None = None,
    program_id: uuid.UUID | None = None,
    application_cycle: str = APPLICATION_CYCLE,
) -> tuple[User, Application, list[ApplicationTask]]:
    owner = user or create_random_user(db)
    if program_id is None:
        program_id = create_random_program(db).id
    application, tasks = create_application(
        session=db,
        user_id=owner.id,
        application_in=ApplicationCreate(
            program_id=program_id, application_cycle=application_cycle
        ),
    )
    return owner, application, tasks


def complete_required_tasks(
    db: Session, *, user: User, application_id: uuid.UUID
) -> None:
    for task in list_tasks(session=db, application_id=application_id):
        if task.is_required and task.status is not TaskStatus.DONE:
            update_task(
                session=db,
                user_id=user.id,
                task_id=task.id,
                task_in=TaskUpdate(version=task.version, status=TaskStatus.DONE),
            )


def move_to(
    db: Session,
    *,
    user: User,
    application: Application,
    target: ApplicationStatus,
    confirm: bool = True,
) -> Application:
    return update_application(
        session=db,
        user_id=user.id,
        application_id=application.id,
        application_in=ApplicationUpdate(
            version=application.version, status=target, confirm=confirm
        ),
    )


def advance_to_submitted(
    db: Session, *, user: User, application: Application
) -> Application:
    application = move_to(
        db, user=user, application=application, target=ApplicationStatus.PREPARING
    )
    complete_required_tasks(db, user=user, application_id=application.id)
    db.refresh(application)
    application = move_to(
        db,
        user=user,
        application=application,
        target=ApplicationStatus.READY_TO_SUBMIT,
    )
    return move_to(
        db, user=user, application=application, target=ApplicationStatus.SUBMITTED
    )
