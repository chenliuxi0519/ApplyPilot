import json
import uuid

import pytest
from sqlmodel import Session

from app.harness import (
    PermissionLevel,
    ToolErrorCode,
    ToolExecutionError,
    ToolRegistry,
)
from app.modules.applications.models import (
    ApplicationStatus,
    TaskSource,
    TaskStatus,
    TaskType,
)
from app.modules.applications.service import list_tasks
from app.modules.applications.state_machine import HIGH_RISK_TRANSITIONS
from app.tools.applications import (
    HIGH_RISK_TARGET_STATUSES,
    UpdateApplicationStatusInput,
    escalate_application_status,
)
from tests.tools.conftest import make_context, run_tool
from tests.utils.application import create_application_for
from tests.utils.program import APPLICATION_CYCLE, create_random_program
from tests.utils.user import create_random_user


def test_create_application_returns_tasks_and_readiness(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    program = create_random_program(db)
    ctx = make_context(db, user)

    output = run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="create_application",
        arguments={
            "program_id": str(program.id),
            "application_cycle": APPLICATION_CYCLE,
        },
    )

    assert output.application.status is ApplicationStatus.SHORTLISTED
    assert output.application.version == 1
    assert len(output.tasks) == 6
    assert output.readiness.is_ready is False
    assert output.readiness.required_total == 4
    assert set(output.readiness.blocking_task_types) == {
        TaskType.CV,
        TaskType.PERSONAL_STATEMENT,
        TaskType.TRANSCRIPT,
        TaskType.APPLICATION_FORM,
    }


def test_duplicate_application_maps_to_conflict(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    program = create_random_program(db)
    ctx = make_context(db, user)
    arguments = {
        "program_id": str(program.id),
        "application_cycle": APPLICATION_CYCLE,
    }
    first = run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="create_application",
        arguments=arguments,
    )

    with pytest.raises(ToolExecutionError) as error:
        run_tool(
            registry=registry,
            ctx=ctx,
            tool_name="create_application",
            arguments=arguments,
        )
    assert error.value.code is ToolErrorCode.CONFLICT
    assert error.value.details is not None
    assert error.value.details["existing_application_id"] == str(
        first.application.application_id
    )


def test_unknown_program_maps_to_not_found(db: Session, registry: ToolRegistry) -> None:
    ctx = make_context(db, create_random_user(db))
    with pytest.raises(ToolExecutionError) as error:
        run_tool(
            registry=registry,
            ctx=ctx,
            tool_name="create_application",
            arguments={
                "program_id": str(uuid.uuid4()),
                "application_cycle": APPLICATION_CYCLE,
            },
        )
    assert error.value.code is ToolErrorCode.NOT_FOUND


def test_created_task_is_attributed_to_the_user(
    db: Session, registry: ToolRegistry
) -> None:
    user, application, _ = create_application_for(db)
    ctx = make_context(db, user)

    output = run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="create_application_task",
        arguments={
            "application_id": str(application.id),
            "task": {"task_type": "other", "title": "Portfolio"},
        },
    )

    assert output.task.title == "Portfolio"
    created = next(
        task
        for task in list_tasks(session=db, application_id=application.id)
        if task.id == output.task.task_id
    )
    assert created.source is TaskSource.USER


def test_updating_a_task_reports_the_resulting_application_state(
    db: Session, registry: ToolRegistry
) -> None:
    user, application, tasks = create_application_for(db)
    ctx = make_context(db, user)
    cv = next(task for task in tasks if task.task_type is TaskType.CV)

    output = run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="update_application_task",
        arguments={
            "task_id": str(cv.id),
            "update": {"version": cv.version, "status": "done"},
        },
    )

    assert output.task.status is TaskStatus.DONE
    assert output.task.version == 2
    assert output.application.application_id == application.id
    assert output.readiness.required_done == 1
    assert output.readiness.is_ready is False


def test_stale_version_maps_to_conflict(db: Session, registry: ToolRegistry) -> None:
    user, _, tasks = create_application_for(db)
    ctx = make_context(db, user)
    cv = next(task for task in tasks if task.task_type is TaskType.CV)
    task_id = str(cv.id)

    stale_version = cv.version

    run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="update_application_task",
        arguments={
            "task_id": task_id,
            "update": {"version": stale_version, "status": "in_progress"},
        },
    )

    with pytest.raises(ToolExecutionError) as error:
        run_tool(
            registry=registry,
            ctx=ctx,
            tool_name="update_application_task",
            arguments={
                "task_id": task_id,
                "update": {"version": stale_version, "status": "done"},
            },
        )
    assert error.value.code is ToolErrorCode.CONFLICT


def test_a_tool_call_cannot_touch_another_users_task(
    db: Session, registry: ToolRegistry
) -> None:
    _, application, tasks = create_application_for(db)
    intruder = create_random_user(db)
    cv = next(task for task in tasks if task.task_type is TaskType.CV)

    with pytest.raises(ToolExecutionError) as error:
        run_tool(
            registry=registry,
            ctx=make_context(db, intruder),
            tool_name="update_application_task",
            arguments={
                "task_id": str(cv.id),
                "update": {"version": cv.version, "status": "done"},
            },
        )
    assert error.value.code is ToolErrorCode.NOT_FOUND

    db.refresh(cv)
    assert cv.status is TaskStatus.TODO


def test_a_tool_call_cannot_add_a_task_to_another_users_application(
    db: Session, registry: ToolRegistry
) -> None:
    _, application, _ = create_application_for(db)
    intruder = create_random_user(db)

    with pytest.raises(ToolExecutionError) as error:
        run_tool(
            registry=registry,
            ctx=make_context(db, intruder),
            tool_name="create_application_task",
            arguments={
                "application_id": str(application.id),
                "task": {"task_type": "other", "title": "Injected"},
            },
        )
    assert error.value.code is ToolErrorCode.NOT_FOUND
    assert len(list_tasks(session=db, application_id=application.id)) == 6


def test_status_tool_is_registered_with_a_serializable_schema(
    registry: ToolRegistry,
) -> None:
    definition = registry.get("update_application_status")
    assert definition.permission_level is PermissionLevel.LOW_RISK_WRITE
    assert sorted(definition.input_schema["properties"]) == [
        "application_id",
        "target_status",
        "version",
    ]
    json.dumps(definition.to_llm_schema())


@pytest.mark.parametrize(
    "target",
    [
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.PREPARING,
        ApplicationStatus.READY_TO_SUBMIT,
        ApplicationStatus.RESULT_PENDING,
    ],
)
def test_reversible_targets_stay_low_risk(target: ApplicationStatus) -> None:
    payload = UpdateApplicationStatusInput(
        application_id=uuid.uuid4(), target_status=target, version=1
    )
    assert escalate_application_status(payload) is PermissionLevel.LOW_RISK_WRITE


@pytest.mark.parametrize(
    "target",
    [
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.OFFERED,
        ApplicationStatus.REJECTED,
    ],
)
def test_real_world_assertions_escalate(target: ApplicationStatus) -> None:
    payload = UpdateApplicationStatusInput(
        application_id=uuid.uuid4(), target_status=target, version=1
    )
    assert escalate_application_status(payload) is PermissionLevel.HIGH_RISK_WRITE


def test_the_tool_is_at_least_as_strict_as_the_domain() -> None:
    assert set(HIGH_RISK_TRANSITIONS) <= HIGH_RISK_TARGET_STATUSES


def test_status_change_reports_both_sides_and_the_program(
    db: Session, registry: ToolRegistry
) -> None:
    user, application, _ = create_application_for(db)
    ctx = make_context(db, user)

    version_before = application.version

    output = run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="update_application_status",
        arguments={
            "application_id": str(application.id),
            "target_status": "preparing",
            "version": version_before,
        },
    )

    assert output.previous_status is ApplicationStatus.SHORTLISTED
    assert output.current_status is ApplicationStatus.PREPARING
    assert output.version == version_before + 1
    assert output.program_name
    assert output.readiness.required_total == 4


def test_status_change_rejects_an_illegal_transition(
    db: Session, registry: ToolRegistry
) -> None:
    user, application, _ = create_application_for(db)
    ctx = make_context(db, user)

    with pytest.raises(ToolExecutionError) as error:
        run_tool(
            registry=registry,
            ctx=ctx,
            tool_name="update_application_status",
            arguments={
                "application_id": str(application.id),
                "target_status": "submitted",
                "version": application.version,
            },
        )
    assert error.value.code is ToolErrorCode.CONFLICT


def test_status_change_rejects_a_stale_version(
    db: Session, registry: ToolRegistry
) -> None:
    user, application, _ = create_application_for(db)
    ctx = make_context(db, user)

    with pytest.raises(ToolExecutionError) as error:
        run_tool(
            registry=registry,
            ctx=ctx,
            tool_name="update_application_status",
            arguments={
                "application_id": str(application.id),
                "target_status": "preparing",
                "version": application.version + 5,
            },
        )
    assert error.value.code is ToolErrorCode.CONFLICT


def test_status_change_cannot_touch_another_users_application(
    db: Session, registry: ToolRegistry
) -> None:
    _, application, _ = create_application_for(db)
    intruder = create_random_user(db)

    with pytest.raises(ToolExecutionError) as error:
        run_tool(
            registry=registry,
            ctx=make_context(db, intruder),
            tool_name="update_application_status",
            arguments={
                "application_id": str(application.id),
                "target_status": "preparing",
                "version": application.version,
            },
        )
    assert error.value.code is ToolErrorCode.NOT_FOUND
