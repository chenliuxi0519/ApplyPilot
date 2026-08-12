import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import User
from app.modules.applications.models import ApplicationStatus, TaskStatus, TaskType
from app.modules.applications.service import list_tasks
from tests.utils.application import advance_to_submitted, create_application_for
from tests.utils.program import APPLICATION_CYCLE, create_random_program
from tests.utils.user import authentication_token_from_email, create_random_user

APPLICATIONS_URL = f"{settings.API_V1_STR}/applications/"
TASKS_URL = f"{settings.API_V1_STR}/application-tasks"


def _owner(client: TestClient, db: Session) -> tuple[User, dict[str, str]]:
    user = create_random_user(db)
    headers = authentication_token_from_email(client=client, email=user.email, db=db)
    return user, headers


def test_list_requires_authentication(client: TestClient) -> None:
    assert client.get(APPLICATIONS_URL).status_code == 401


def test_user_task_can_be_deleted_over_http(client: TestClient, db: Session) -> None:
    user, headers = _owner(client, db)
    _, application, _ = create_application_for(db, user=user)
    created = client.post(
        f"{APPLICATIONS_URL}{application.id}/tasks",
        headers=headers,
        json={"task_type": "other", "title": "Prepare interview notes"},
    )
    assert created.status_code == 200
    task = created.json()

    deleted = client.delete(
        f"{TASKS_URL}/{task['id']}",
        headers=headers,
        params={"version": task["version"]},
    )

    assert deleted.status_code == 200
    assert all(
        item.id != uuid.UUID(task["id"])
        for item in list_tasks(session=db, application_id=application.id)
    )


def test_create_returns_application_with_tasks_and_readiness(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    response = client.post(
        APPLICATIONS_URL,
        headers=normal_user_token_headers,
        json={
            "program_id": str(program.id),
            "application_cycle": APPLICATION_CYCLE,
        },
    )

    assert response.status_code == 200
    content = response.json()
    assert content["status"] == "shortlisted"
    assert content["version"] == 1
    assert len(content["tasks"]) == 6
    assert content["readiness"]["is_ready"] is False
    assert content["readiness"]["required_total"] == 4
    assert len(content["readiness"]["blocking_tasks"]) == 4


def test_duplicate_create_returns_409(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    body = {
        "program_id": str(program.id),
        "application_cycle": APPLICATION_CYCLE,
    }
    first = client.post(APPLICATIONS_URL, headers=normal_user_token_headers, json=body)
    assert first.status_code == 200

    duplicate = client.post(
        APPLICATIONS_URL, headers=normal_user_token_headers, json=body
    )
    assert duplicate.status_code == 409
    detail = duplicate.json()["detail"]
    assert detail["existing_application_id"] == first.json()["id"]


def test_create_for_unknown_program_returns_404(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    response = client.post(
        APPLICATIONS_URL,
        headers=normal_user_token_headers,
        json={
            "program_id": str(uuid.uuid4()),
            "application_cycle": APPLICATION_CYCLE,
        },
    )
    assert response.status_code == 404


def test_another_users_application_is_reported_as_missing(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    _, application, _ = create_application_for(db)
    response = client.get(
        f"{APPLICATIONS_URL}{application.id}", headers=normal_user_token_headers
    )
    assert response.status_code == 404


def test_list_is_scoped_to_the_caller(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    create_application_for(db)
    program = create_random_program(db)
    client.post(
        APPLICATIONS_URL,
        headers=normal_user_token_headers,
        json={
            "program_id": str(program.id),
            "application_cycle": APPLICATION_CYCLE,
        },
    )

    response = client.get(
        APPLICATIONS_URL,
        headers=normal_user_token_headers,
        params={"program_id": str(program.id)},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_patch_without_version_is_rejected(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    created = client.post(
        APPLICATIONS_URL,
        headers=normal_user_token_headers,
        json={
            "program_id": str(program.id),
            "application_cycle": APPLICATION_CYCLE,
        },
    ).json()

    response = client.patch(
        f"{APPLICATIONS_URL}{created['id']}",
        headers=normal_user_token_headers,
        json={"status": "preparing"},
    )
    assert response.status_code == 422


def test_stale_version_returns_409(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    created = client.post(
        APPLICATIONS_URL,
        headers=normal_user_token_headers,
        json={
            "program_id": str(program.id),
            "application_cycle": APPLICATION_CYCLE,
        },
    ).json()

    ok = client.patch(
        f"{APPLICATIONS_URL}{created['id']}",
        headers=normal_user_token_headers,
        json={"version": created["version"], "status": "preparing"},
    )
    assert ok.status_code == 200
    assert ok.json()["version"] == 2

    stale = client.patch(
        f"{APPLICATIONS_URL}{created['id']}",
        headers=normal_user_token_headers,
        json={"version": created["version"], "status": "shortlisted"},
    )
    assert stale.status_code == 409


def test_illegal_transition_returns_409(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    created = client.post(
        APPLICATIONS_URL,
        headers=normal_user_token_headers,
        json={
            "program_id": str(program.id),
            "application_cycle": APPLICATION_CYCLE,
        },
    ).json()

    response = client.patch(
        f"{APPLICATIONS_URL}{created['id']}",
        headers=normal_user_token_headers,
        json={"version": created["version"], "status": "submitted", "confirm": True},
    )
    assert response.status_code == 409


def test_ready_to_submit_returns_blocking_tasks(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    created = client.post(
        APPLICATIONS_URL,
        headers=normal_user_token_headers,
        json={
            "program_id": str(program.id),
            "application_cycle": APPLICATION_CYCLE,
        },
    ).json()
    preparing = client.patch(
        f"{APPLICATIONS_URL}{created['id']}",
        headers=normal_user_token_headers,
        json={"version": created["version"], "status": "preparing"},
    ).json()

    response = client.patch(
        f"{APPLICATIONS_URL}{created['id']}",
        headers=normal_user_token_headers,
        json={"version": preparing["version"], "status": "ready_to_submit"},
    )

    assert response.status_code == 409
    readiness = response.json()["detail"]["readiness"]
    assert readiness["is_ready"] is False
    assert len(readiness["blocking_tasks"]) == 4


def test_mark_submitted_demands_confirmation(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    created = client.post(
        APPLICATIONS_URL,
        headers=normal_user_token_headers,
        json={
            "program_id": str(program.id),
            "application_cycle": APPLICATION_CYCLE,
        },
    ).json()
    application_id = created["id"]

    current = client.patch(
        f"{APPLICATIONS_URL}{application_id}",
        headers=normal_user_token_headers,
        json={"version": created["version"], "status": "preparing"},
    ).json()

    for task in current["tasks"]:
        if task["is_required"]:
            done = client.patch(
                f"{TASKS_URL}/{task['id']}",
                headers=normal_user_token_headers,
                json={"version": task["version"], "status": "done"},
            )
            assert done.status_code == 200

    ready = client.patch(
        f"{APPLICATIONS_URL}{application_id}",
        headers=normal_user_token_headers,
        json={"version": current["version"], "status": "ready_to_submit"},
    ).json()
    assert ready["status"] == "ready_to_submit"
    assert ready["readiness"]["is_ready"] is True

    unconfirmed = client.patch(
        f"{APPLICATIONS_URL}{application_id}",
        headers=normal_user_token_headers,
        json={"version": ready["version"], "status": "submitted"},
    )
    assert unconfirmed.status_code == 409
    detail = unconfirmed.json()["detail"]
    assert detail["requires_confirmation"] is True
    assert detail["action"] == "mark_submitted"
    assert detail["effects"]

    confirmed = client.patch(
        f"{APPLICATIONS_URL}{application_id}",
        headers=normal_user_token_headers,
        json={"version": ready["version"], "status": "submitted", "confirm": True},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "submitted"
    assert confirmed.json()["submitted_at"] is not None


def test_required_task_cannot_be_reopened_after_submission_over_http(
    client: TestClient, db: Session
) -> None:
    user, headers = _owner(client, db)
    _, application, _ = create_application_for(db, user=user)
    application = advance_to_submitted(db, user=user, application=application)

    cv = next(
        task
        for task in list_tasks(session=db, application_id=application.id)
        if task.task_type is TaskType.CV
    )
    response = client.patch(
        f"{TASKS_URL}/{cv.id}",
        headers=headers,
        json={"version": cv.version, "status": "todo"},
    )
    assert response.status_code == 409


def test_task_creation_and_update_over_http(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    created = client.post(
        APPLICATIONS_URL,
        headers=normal_user_token_headers,
        json={
            "program_id": str(program.id),
            "application_cycle": APPLICATION_CYCLE,
        },
    ).json()

    task = client.post(
        f"{APPLICATIONS_URL}{created['id']}/tasks",
        headers=normal_user_token_headers,
        json={"task_type": "other", "title": "Portfolio", "is_required": True},
    )
    assert task.status_code == 200
    assert task.json()["source"] == "user"

    listed = client.get(
        f"{APPLICATIONS_URL}{created['id']}/tasks", headers=normal_user_token_headers
    )
    assert listed.status_code == 200
    assert listed.json()["count"] == 7

    updated = client.patch(
        f"{TASKS_URL}/{task.json()['id']}",
        headers=normal_user_token_headers,
        json={"version": task.json()["version"], "status": "done"},
    )
    assert updated.status_code == 200
    assert updated.json()["completed_at"] is not None


def test_another_users_task_is_reported_as_missing(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    _, application, _ = create_application_for(db)
    task = list_tasks(session=db, application_id=application.id)[0]

    response = client.patch(
        f"{TASKS_URL}/{task.id}",
        headers=normal_user_token_headers,
        json={"version": task.version, "status": "done"},
    )
    assert response.status_code == 404


def test_delete_requires_confirmation_over_http(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    created = client.post(
        APPLICATIONS_URL,
        headers=normal_user_token_headers,
        json={
            "program_id": str(program.id),
            "application_cycle": APPLICATION_CYCLE,
        },
    ).json()

    unconfirmed = client.delete(
        f"{APPLICATIONS_URL}{created['id']}",
        headers=normal_user_token_headers,
        params={"version": created["version"]},
    )
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["detail"]["action"] == "delete_application"

    confirmed = client.delete(
        f"{APPLICATIONS_URL}{created['id']}",
        headers=normal_user_token_headers,
        params={"version": created["version"], "confirm": True},
    )
    assert confirmed.status_code == 200

    gone = client.get(
        f"{APPLICATIONS_URL}{created['id']}", headers=normal_user_token_headers
    )
    assert gone.status_code == 404


def test_status_filter(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    response = client.get(
        APPLICATIONS_URL,
        headers=normal_user_token_headers,
        params={"status": ApplicationStatus.OFFERED.value},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_task_status_enum_is_validated(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    created = client.post(
        APPLICATIONS_URL,
        headers=normal_user_token_headers,
        json={
            "program_id": str(program.id),
            "application_cycle": APPLICATION_CYCLE,
        },
    ).json()
    task = created["tasks"][0]

    response = client.patch(
        f"{TASKS_URL}/{task['id']}",
        headers=normal_user_token_headers,
        json={"version": task["version"], "status": TaskStatus.DONE.value + "x"},
    )
    assert response.status_code == 422


def test_null_task_title_is_rejected(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    created = client.post(
        APPLICATIONS_URL,
        headers=normal_user_token_headers,
        json={
            "program_id": str(program.id),
            "application_cycle": APPLICATION_CYCLE,
        },
    ).json()
    task = created["tasks"][0]

    response = client.patch(
        f"{TASKS_URL}/{task['id']}",
        headers=normal_user_token_headers,
        json={"version": task["version"], "title": None},
    )
    assert response.status_code == 422
