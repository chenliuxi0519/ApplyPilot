import uuid
from datetime import UTC, date, datetime

import pytest
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
from app.modules.applications.service import (
    ApplicationAlreadyExistsError,
    ApplicationNotFoundError,
    ConfirmationRequiredError,
    NotReadyError,
    ProgramNotFoundError,
    TaskDeletionError,
    TaskTransitionError,
    TransitionError,
    VersionConflictError,
    create_application,
    create_task,
    delete_application,
    delete_task,
    evaluate_readiness,
    get_application,
    list_applications,
    list_tasks,
    update_application,
    update_task,
)
from app.modules.applications.state_machine import HighRiskAction
from app.modules.programs.models import (
    EvidenceSourceType,
    Program,
    RequirementFieldName,
)
from app.modules.programs.schemas import EvidenceCreate
from app.modules.programs.service import (
    accept_evidence,
    ingest_evidence,
)
from tests.utils.application import (
    advance_to_submitted,
    complete_required_tasks,
    create_application_for,
    move_to,
)
from tests.utils.program import (
    APPLICATION_CYCLE,
    create_random_program,
    ielts_evidence,
)
from tests.utils.user import create_random_user


def _task_of(tasks: list[ApplicationTask], task_type: TaskType) -> ApplicationTask:
    return next(task for task in tasks if task.task_type is task_type)


def test_create_generates_the_base_template(db: Session) -> None:
    _, application, tasks = create_application_for(db)

    assert application.status is ApplicationStatus.SHORTLISTED
    assert application.version == 1
    assert {task.task_type for task in tasks} == {
        TaskType.CV,
        TaskType.PERSONAL_STATEMENT,
        TaskType.TRANSCRIPT,
        TaskType.APPLICATION_FORM,
        TaskType.RECOMMENDATION,
        TaskType.LANGUAGE_SCORE,
    }
    assert all(task.status is TaskStatus.TODO for task in tasks)
    assert all(task.completed_at is None for task in tasks)


def test_recommendation_is_optional_without_verified_evidence(db: Session) -> None:
    _, _, tasks = create_application_for(db)
    assert _task_of(tasks, TaskType.RECOMMENDATION).is_required is False


def test_language_task_is_optional_without_a_verified_requirement(
    db: Session,
) -> None:
    _, _, tasks = create_application_for(db)
    language = _task_of(tasks, TaskType.LANGUAGE_SCORE)
    assert language.is_required is False
    assert language.source is TaskSource.TEMPLATE
    assert language.source_requirement_id is None


def test_language_task_becomes_required_when_the_requirement_is_verified(
    db: Session,
) -> None:
    program = create_random_program(db)
    published = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )

    _, _, tasks = create_application_for(db, program_id=program.id)
    language = _task_of(tasks, TaskType.LANGUAGE_SCORE)

    assert language.is_required is True
    assert language.source is TaskSource.PROGRAM_REQUIREMENT
    assert language.source_requirement_id == published.requirement.id


def test_language_task_stays_optional_while_the_requirement_is_in_conflict(
    db: Session,
) -> None:
    program = create_random_program(db)
    ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )

    ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.0")
    )

    _, _, tasks = create_application_for(db, program_id=program.id)
    assert _task_of(tasks, TaskType.LANGUAGE_SCORE).is_required is False


def test_language_task_is_required_again_after_the_conflict_is_resolved(
    db: Session,
) -> None:
    reviewer = create_random_user(db)
    program = create_random_program(db)
    ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )
    conflict = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.0")
    )
    accept_evidence(
        session=db, evidence_id=conflict.evidence.id, reviewer_id=reviewer.id
    )

    _, _, tasks = create_application_for(db, program_id=program.id)
    assert _task_of(tasks, TaskType.LANGUAGE_SCORE).is_required is True


def test_target_deadline_is_prefilled_from_a_verified_requirement(
    db: Session,
) -> None:
    program = create_random_program(db)
    ingest_evidence(
        session=db,
        program_id=program.id,
        evidence_in=EvidenceCreate(
            application_cycle=APPLICATION_CYCLE,
            field_name=RequirementFieldName.APPLICATION_DEADLINE,
            date_value=date(2027, 1, 15),
            source_url="https://example.edu/deadlines",
            source_type=EvidenceSourceType.ADMISSION_PAGE,
            captured_at=datetime(2026, 1, 15, tzinfo=UTC),
        ),
    )

    _, application, tasks = create_application_for(db, program_id=program.id)

    assert application.target_deadline == date(2027, 1, 15)
    assert all(task.due_date == date(2027, 1, 15) for task in tasks)


def test_explicit_deadline_wins_over_the_catalog(db: Session) -> None:
    program = create_random_program(db)
    user = create_random_user(db)
    application, _ = create_application(
        session=db,
        user_id=user.id,
        application_in=ApplicationCreate(
            program_id=program.id,
            application_cycle=APPLICATION_CYCLE,
            target_deadline=date(2026, 12, 1),
        ),
    )
    assert application.target_deadline == date(2026, 12, 1)


def test_duplicate_application_is_refused_by_the_database(db: Session) -> None:
    user, application, _ = create_application_for(db)

    with pytest.raises(ApplicationAlreadyExistsError) as error:
        create_application(
            session=db,
            user_id=user.id,
            application_in=ApplicationCreate(
                program_id=application.program_id,
                application_cycle=APPLICATION_CYCLE,
            ),
        )
    assert error.value.existing_id == application.id


def test_same_program_in_another_cycle_is_allowed(db: Session) -> None:
    user, application, _ = create_application_for(db)
    other, _ = create_application(
        session=db,
        user_id=user.id,
        application_in=ApplicationCreate(
            program_id=application.program_id, application_cycle="2025/26"
        ),
    )
    assert other.id != application.id


def test_create_for_unknown_program_raises(db: Session) -> None:
    user = create_random_user(db)
    with pytest.raises(ProgramNotFoundError):
        create_application(
            session=db,
            user_id=user.id,
            application_in=ApplicationCreate(
                program_id=uuid.uuid4(), application_cycle=APPLICATION_CYCLE
            ),
        )


def test_readiness_ignores_optional_tasks(db: Session) -> None:
    user, application, _ = create_application_for(db)
    complete_required_tasks(db, user=user, application_id=application.id)

    readiness = evaluate_readiness(
        list_tasks(session=db, application_id=application.id)
    )
    assert readiness.is_ready is True
    assert readiness.required_total == 4
    assert readiness.required_done == 4
    assert readiness.blocking_tasks == []


def test_readiness_reports_blocking_tasks(db: Session) -> None:
    _, application, tasks = create_application_for(db)
    readiness = evaluate_readiness(tasks)

    assert readiness.is_ready is False
    assert readiness.required_done == 0
    assert {task.task_type for task in readiness.blocking_tasks} == {
        TaskType.CV,
        TaskType.PERSONAL_STATEMENT,
        TaskType.TRANSCRIPT,
        TaskType.APPLICATION_FORM,
    }


def test_application_without_required_tasks_is_not_ready() -> None:
    assert evaluate_readiness([]).is_ready is False


def test_ready_to_submit_is_refused_while_tasks_are_open(db: Session) -> None:
    user, application, _ = create_application_for(db)
    application = move_to(
        db, user=user, application=application, target=ApplicationStatus.PREPARING
    )

    with pytest.raises(NotReadyError) as error:
        move_to(
            db,
            user=user,
            application=application,
            target=ApplicationStatus.READY_TO_SUBMIT,
        )
    assert error.value.readiness.required_done == 0
    assert len(error.value.readiness.blocking_tasks) == 4


def test_ready_to_submit_succeeds_once_required_tasks_are_done(
    db: Session,
) -> None:
    user, application, _ = create_application_for(db)
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
    assert application.status is ApplicationStatus.READY_TO_SUBMIT


def test_reopening_a_required_task_demotes_a_ready_application(db: Session) -> None:
    user, application, _ = create_application_for(db)
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

    cv = _task_of(list_tasks(session=db, application_id=application.id), TaskType.CV)
    _, refreshed = update_task(
        session=db,
        user_id=user.id,
        task_id=cv.id,
        task_in=TaskUpdate(version=cv.version, status=TaskStatus.TODO),
    )

    assert refreshed.status is ApplicationStatus.PREPARING


def test_reopening_an_optional_task_does_not_demote(db: Session) -> None:
    user, application, _ = create_application_for(db)
    application = move_to(
        db, user=user, application=application, target=ApplicationStatus.PREPARING
    )
    complete_required_tasks(db, user=user, application_id=application.id)
    tasks = list_tasks(session=db, application_id=application.id)
    recommendation = _task_of(tasks, TaskType.RECOMMENDATION)
    update_task(
        session=db,
        user_id=user.id,
        task_id=recommendation.id,
        task_in=TaskUpdate(version=recommendation.version, status=TaskStatus.DONE),
    )
    db.refresh(application)
    application = move_to(
        db,
        user=user,
        application=application,
        target=ApplicationStatus.READY_TO_SUBMIT,
    )

    db.refresh(recommendation)
    _, refreshed = update_task(
        session=db,
        user_id=user.id,
        task_id=recommendation.id,
        task_in=TaskUpdate(version=recommendation.version, status=TaskStatus.TODO),
    )
    assert refreshed.status is ApplicationStatus.READY_TO_SUBMIT


def test_illegal_transition_is_refused(db: Session) -> None:
    user, application, _ = create_application_for(db)
    with pytest.raises(TransitionError):
        move_to(
            db,
            user=user,
            application=application,
            target=ApplicationStatus.SUBMITTED,
        )


def test_self_transition_is_refused(db: Session) -> None:
    user, application, _ = create_application_for(db)
    with pytest.raises(TransitionError):
        move_to(
            db,
            user=user,
            application=application,
            target=ApplicationStatus.SHORTLISTED,
        )


def test_marking_submitted_requires_confirmation(db: Session) -> None:
    user, application, _ = create_application_for(db)
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

    with pytest.raises(ConfirmationRequiredError) as error:
        move_to(
            db,
            user=user,
            application=application,
            target=ApplicationStatus.SUBMITTED,
            confirm=False,
        )
    assert error.value.action is HighRiskAction.MARK_SUBMITTED
    assert error.value.effects

    db.refresh(application)
    assert application.status is ApplicationStatus.READY_TO_SUBMIT
    assert application.submitted_at is None


def test_submitting_records_the_timestamp(db: Session) -> None:
    user, application, _ = create_application_for(db)
    application = advance_to_submitted(db, user=user, application=application)

    assert application.status is ApplicationStatus.SUBMITTED
    assert application.submitted_at is not None


def test_submitted_can_go_straight_to_offered(db: Session) -> None:
    user, application, _ = create_application_for(db)
    application = advance_to_submitted(db, user=user, application=application)
    application = move_to(
        db, user=user, application=application, target=ApplicationStatus.OFFERED
    )
    assert application.status is ApplicationStatus.OFFERED


def test_withdraw_requires_confirmation(db: Session) -> None:
    user, application, _ = create_application_for(db)
    with pytest.raises(ConfirmationRequiredError):
        move_to(
            db,
            user=user,
            application=application,
            target=ApplicationStatus.WITHDRAWN,
            confirm=False,
        )


def test_withdrawn_application_can_be_reopened(db: Session) -> None:
    user, application, _ = create_application_for(db)
    application = move_to(
        db, user=user, application=application, target=ApplicationStatus.WITHDRAWN
    )
    application = move_to(
        db, user=user, application=application, target=ApplicationStatus.SHORTLISTED
    )
    assert application.status is ApplicationStatus.SHORTLISTED


def test_rejected_is_terminal(db: Session) -> None:
    user, application, _ = create_application_for(db)
    application = advance_to_submitted(db, user=user, application=application)
    application = move_to(
        db, user=user, application=application, target=ApplicationStatus.REJECTED
    )
    with pytest.raises(TransitionError):
        move_to(
            db,
            user=user,
            application=application,
            target=ApplicationStatus.WITHDRAWN,
        )


def test_required_task_cannot_be_reopened_after_submission(db: Session) -> None:
    user, application, _ = create_application_for(db)
    application = advance_to_submitted(db, user=user, application=application)

    cv = _task_of(list_tasks(session=db, application_id=application.id), TaskType.CV)
    with pytest.raises(TaskTransitionError):
        update_task(
            session=db,
            user_id=user.id,
            task_id=cv.id,
            task_in=TaskUpdate(version=cv.version, status=TaskStatus.TODO),
        )

    db.refresh(cv)
    assert cv.status is TaskStatus.DONE


def test_optional_task_can_still_move_after_submission(db: Session) -> None:
    user, application, _ = create_application_for(db)
    application = advance_to_submitted(db, user=user, application=application)

    recommendation = _task_of(
        list_tasks(session=db, application_id=application.id), TaskType.RECOMMENDATION
    )
    task, _ = update_task(
        session=db,
        user_id=user.id,
        task_id=recommendation.id,
        task_in=TaskUpdate(
            version=recommendation.version, status=TaskStatus.IN_PROGRESS
        ),
    )
    assert task.status is TaskStatus.IN_PROGRESS


def test_new_task_can_be_added_after_submission(db: Session) -> None:
    user, application, _ = create_application_for(db)
    application = advance_to_submitted(db, user=user, application=application)

    task = create_task(
        session=db,
        user_id=user.id,
        application_id=application.id,
        task_in=TaskCreate(task_type=TaskType.OTHER, title="Send supplementary form"),
    )
    assert task.source is TaskSource.USER
    assert task.is_required is False


def test_completing_a_task_sets_and_clears_completed_at(db: Session) -> None:
    user, application, _ = create_application_for(db)
    cv = _task_of(list_tasks(session=db, application_id=application.id), TaskType.CV)

    task, _ = update_task(
        session=db,
        user_id=user.id,
        task_id=cv.id,
        task_in=TaskUpdate(version=cv.version, status=TaskStatus.DONE),
    )
    assert task.completed_at is not None

    task, _ = update_task(
        session=db,
        user_id=user.id,
        task_id=task.id,
        task_in=TaskUpdate(version=task.version, status=TaskStatus.BLOCKED),
    )
    assert task.completed_at is None


def test_user_created_task_can_be_deleted(db: Session) -> None:
    user, application, _ = create_application_for(db)
    task = create_task(
        session=db,
        user_id=user.id,
        application_id=application.id,
        task_in=TaskCreate(task_type=TaskType.OTHER, title="Book interview room"),
    )
    delete_task(
        session=db,
        user_id=user.id,
        task_id=task.id,
        version=task.version,
    )
    assert db.get(ApplicationTask, task.id) is None


def test_generated_task_cannot_be_deleted(db: Session) -> None:
    user, _, tasks = create_application_for(db)
    task = tasks[0]
    with pytest.raises(TaskDeletionError):
        delete_task(
            session=db,
            user_id=user.id,
            task_id=task.id,
            version=task.version,
        )


def test_another_user_cannot_reach_the_application(db: Session) -> None:
    _, application, tasks = create_application_for(db)
    intruder = create_random_user(db)

    with pytest.raises(ApplicationNotFoundError):
        get_application(session=db, user_id=intruder.id, application_id=application.id)
    with pytest.raises(ApplicationNotFoundError):
        update_task(
            session=db,
            user_id=intruder.id,
            task_id=tasks[0].id,
            task_in=TaskUpdate(version=tasks[0].version, status=TaskStatus.DONE),
        )


def test_list_only_returns_own_applications(db: Session) -> None:
    user, application, _ = create_application_for(db)
    create_application_for(db)

    rows, count = list_applications(session=db, user_id=user.id)
    assert count == 1
    assert [row.id for row in rows] == [application.id]


def test_stale_version_is_refused(db: Session) -> None:
    user, application, _ = create_application_for(db)
    stale_version = application.version
    move_to(db, user=user, application=application, target=ApplicationStatus.PREPARING)

    with pytest.raises(VersionConflictError):
        update_application(
            session=db,
            user_id=user.id,
            application_id=application.id,
            application_in=ApplicationUpdate(
                version=stale_version, target_deadline=date(2027, 1, 1)
            ),
        )


def test_version_increments_on_change_only(db: Session) -> None:
    user, application, _ = create_application_for(db)
    assert application.version == 1

    application = update_application(
        session=db,
        user_id=user.id,
        application_id=application.id,
        application_in=ApplicationUpdate(
            version=application.version, target_deadline=date(2027, 1, 1)
        ),
    )
    assert application.version == 2

    application = update_application(
        session=db,
        user_id=user.id,
        application_id=application.id,
        application_in=ApplicationUpdate(
            version=application.version, target_deadline=date(2027, 1, 1)
        ),
    )
    assert application.version == 2


def test_delete_requires_confirmation_and_removes_tasks(db: Session) -> None:
    user, application, _ = create_application_for(db)

    with pytest.raises(ConfirmationRequiredError):
        delete_application(
            session=db,
            user_id=user.id,
            application_id=application.id,
            version=application.version,
            confirmed=False,
        )

    delete_application(
        session=db,
        user_id=user.id,
        application_id=application.id,
        version=application.version,
        confirmed=True,
    )

    assert db.get(Application, application.id) is None
    assert (
        db.exec(
            select(ApplicationTask).where(
                col(ApplicationTask.application_id) == application.id
            )
        ).all()
        == []
    )


def test_delete_with_a_stale_version_is_refused(db: Session) -> None:
    user, application, _ = create_application_for(db)
    with pytest.raises(VersionConflictError):
        delete_application(
            session=db,
            user_id=user.id,
            application_id=application.id,
            version=application.version + 1,
            confirmed=True,
        )
    assert db.get(Application, application.id) is not None


def test_deleting_the_user_removes_the_application(db: Session) -> None:
    user, application, _ = create_application_for(db)
    application_id = application.id

    db.delete(user)
    db.commit()

    db.expunge_all()

    assert db.get(Application, application_id) is None
    assert (
        db.exec(
            select(ApplicationTask).where(
                col(ApplicationTask.application_id) == application_id
            )
        ).all()
        == []
    )


def test_program_with_an_application_cannot_be_deleted(db: Session) -> None:
    _, application, _ = create_application_for(db)
    program = db.get(Program, application.program_id)
    assert program is not None

    db.delete(program)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.get(Program, application.program_id) is not None


def test_database_enforces_unique_user_program_cycle(db: Session) -> None:
    user, application, _ = create_application_for(db)
    db.add(
        Application(
            user_id=user.id,
            program_id=application.program_id,
            application_cycle=APPLICATION_CYCLE,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_rejects_submitted_without_timestamp(db: Session) -> None:
    user = create_random_user(db)
    program = create_random_program(db)
    db.add(
        Application(
            user_id=user.id,
            program_id=program.id,
            application_cycle=APPLICATION_CYCLE,
            status=ApplicationStatus.SUBMITTED,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_rejects_done_task_without_completed_at(db: Session) -> None:
    _, application, _ = create_application_for(db)
    db.add(
        ApplicationTask(
            application_id=application.id,
            task_type=TaskType.OTHER,
            title="Broken",
            status=TaskStatus.DONE,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_rejects_malformed_application_cycle(db: Session) -> None:
    user = create_random_user(db)
    program = create_random_program(db)
    db.add(
        Application(user_id=user.id, program_id=program.id, application_cycle="2026")
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
