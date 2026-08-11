import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlmodel import Session, col, select

from app.core.db import engine
from app.modules.applications.models import Application, TaskStatus
from app.modules.applications.schemas import ApplicationCreate, TaskUpdate
from app.modules.applications.service import (
    ApplicationAlreadyExistsError,
    VersionConflictError,
    create_application,
    list_tasks,
    update_task,
)
from tests.utils.application import create_application_for
from tests.utils.program import APPLICATION_CYCLE, create_random_program
from tests.utils.user import create_random_user


def test_concurrent_creates_leave_one_application(db: Session) -> None:
    user = create_random_user(db)
    program = create_random_program(db)
    user_id = user.id
    program_id = program.id
    outcomes: list[str] = []

    def create() -> None:
        with Session(engine) as session:
            try:
                create_application(
                    session=session,
                    user_id=user_id,
                    application_in=ApplicationCreate(
                        program_id=program_id, application_cycle=APPLICATION_CYCLE
                    ),
                )
                outcomes.append("created")
            except ApplicationAlreadyExistsError:
                outcomes.append("duplicate")

    with ThreadPoolExecutor(max_workers=2) as executor:
        for future in [executor.submit(create), executor.submit(create)]:
            future.result()

    db.expire_all()
    rows = db.exec(
        select(Application)
        .where(col(Application.user_id) == user_id)
        .where(col(Application.program_id) == program_id)
    ).all()

    assert len(rows) == 1
    assert sorted(outcomes) == ["created", "duplicate"]


def test_concurrent_task_updates_reject_the_stale_writer(db: Session) -> None:
    user, application, _ = create_application_for(db)
    task = list_tasks(session=db, application_id=application.id)[0]
    user_id = user.id
    task_id = task.id
    stale_version = task.version
    failures: list[str] = []

    def update(status: TaskStatus, version: int) -> None:
        with Session(engine) as session:
            try:
                update_task(
                    session=session,
                    user_id=user_id,
                    task_id=task_id,
                    task_in=TaskUpdate(version=version, status=status),
                )
            except VersionConflictError:
                failures.append("stale")

    update(TaskStatus.IN_PROGRESS, stale_version)

    update(TaskStatus.DONE, stale_version)

    assert failures == ["stale"]
    db.expire_all()
    refreshed = list_tasks(session=db, application_id=application.id)
    assert next(row for row in refreshed if row.id == task_id).status is (
        TaskStatus.IN_PROGRESS
    )


def test_parallel_task_completion_keeps_versions_consistent(db: Session) -> None:
    user, application, _ = create_application_for(db)
    tasks = [
        (task.id, task.version)
        for task in list_tasks(session=db, application_id=application.id)
        if task.is_required
    ]
    user_id = user.id

    def complete(task_id: uuid.UUID, version: int) -> None:
        with Session(engine) as session:
            update_task(
                session=session,
                user_id=user_id,
                task_id=task_id,
                task_in=TaskUpdate(version=version, status=TaskStatus.DONE),
            )

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(complete, task_id, version) for task_id, version in tasks
        ]
        for future in futures:
            future.result()

    db.expire_all()
    refreshed = list_tasks(session=db, application_id=application.id)
    required = [task for task in refreshed if task.is_required]
    assert all(task.status is TaskStatus.DONE for task in required)
    assert all(task.version == 2 for task in required)
