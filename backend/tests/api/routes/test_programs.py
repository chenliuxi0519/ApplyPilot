import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.modules.programs.service import ingest_evidence
from tests.utils.program import (
    APPLICATION_CYCLE,
    create_random_program,
    create_random_university,
    ielts_evidence,
)

PROGRAMS_URL = f"{settings.API_V1_STR}/programs/"
REQUIREMENTS_URL = f"{settings.API_V1_STR}/requirements"


def _evidence_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "application_cycle": APPLICATION_CYCLE,
        "field_name": "ielts_overall",
        "numeric_value": "6.5",
        "source_url": "https://example.edu/msc-ai/admissions",
        "source_type": "program_page",
        "captured_at": "2026-01-15T00:00:00Z",
    }
    body.update(overrides)
    return body


def test_search_programs_requires_authentication(client: TestClient) -> None:
    response = client.get(PROGRAMS_URL)
    assert response.status_code == 401


def test_search_programs_returns_university(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    university = create_random_university(db)
    program = create_random_program(db, university=university)

    response = client.get(
        PROGRAMS_URL,
        headers=normal_user_token_headers,
        params={"university": university.short_name},
    )

    assert response.status_code == 200
    content = response.json()
    assert content["count"] == 1
    assert content["data"][0]["id"] == str(program.id)
    assert content["data"][0]["university"]["short_name"] == university.short_name


def test_budget_filter_without_currency_is_rejected(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    response = client.get(
        PROGRAMS_URL,
        headers=normal_user_token_headers,
        params={"max_tuition": "50000", "application_cycle": APPLICATION_CYCLE},
    )
    assert response.status_code == 422


def test_read_program_returns_404_for_unknown_id(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/programs/{uuid.uuid4()}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404


def test_read_requirements_is_empty_before_any_evidence(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    response = client.get(
        f"{settings.API_V1_STR}/programs/{program.id}/requirements",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"data": [], "count": 0}


def test_normal_user_cannot_ingest_evidence(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    response = client.post(
        f"{settings.API_V1_STR}/programs/{program.id}/evidence",
        headers=normal_user_token_headers,
        json=_evidence_body(),
    )
    assert response.status_code == 403


def test_superuser_ingests_evidence_and_publishes_requirement(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    response = client.post(
        f"{settings.API_V1_STR}/programs/{program.id}/evidence",
        headers=superuser_token_headers,
        json=_evidence_body(),
    )

    assert response.status_code == 200
    content = response.json()
    assert content["outcome"] == "published_initial"
    assert content["evidence"]["status"] == "verified"
    assert content["requirement"]["status"] == "published"
    assert content["requirement"]["value_type"] == "numeric"
    assert float(content["requirement"]["numeric_value"]) == 6.5


def test_ingest_rejects_a_value_in_the_wrong_slot(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    response = client.post(
        f"{settings.API_V1_STR}/programs/{program.id}/evidence",
        headers=superuser_token_headers,
        json=_evidence_body(numeric_value=None, text_value="6.5 overall"),
    )
    assert response.status_code == 422


def test_ingest_returns_404_for_unknown_program(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/programs/{uuid.uuid4()}/evidence",
        headers=superuser_token_headers,
        json=_evidence_body(),
    )
    assert response.status_code == 404


def test_conflicting_source_is_queued_for_review(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    program = create_random_program(db)
    client.post(
        f"{settings.API_V1_STR}/programs/{program.id}/evidence",
        headers=superuser_token_headers,
        json=_evidence_body(),
    )
    conflict = client.post(
        f"{settings.API_V1_STR}/programs/{program.id}/evidence",
        headers=superuser_token_headers,
        json=_evidence_body(
            numeric_value="7.0", source_url="https://example.edu/english"
        ),
    )

    assert conflict.status_code == 200
    assert conflict.json()["outcome"] == "conflict_recorded"
    assert conflict.json()["requirement"]["status"] == "conflict_pending"

    assert float(conflict.json()["requirement"]["numeric_value"]) == 6.5

    drawer = client.get(
        f"{settings.API_V1_STR}/programs/{program.id}/evidence",
        headers=normal_user_token_headers,
        params={"status": "conflicted"},
    )
    assert drawer.status_code == 200
    assert drawer.json()["count"] == 1

    queue = client.get(
        f"{REQUIREMENTS_URL}/conflicts",
        headers=superuser_token_headers,
        params={"program_id": str(program.id)},
    )
    assert queue.status_code == 200
    assert queue.json()["count"] == 1


def test_normal_user_cannot_read_the_conflict_queue(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{REQUIREMENTS_URL}/conflicts", headers=normal_user_token_headers
    )
    assert response.status_code == 403


def test_superuser_accepts_a_conflict_and_republishes(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )
    conflict = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.0")
    )

    response = client.post(
        f"{REQUIREMENTS_URL}/evidence/{conflict.evidence.id}/accept",
        headers=superuser_token_headers,
        json={"note": "Confirmed on the 2027 admissions page"},
    )

    assert response.status_code == 200
    content = response.json()
    assert content["decision"] == "evidence_accepted"
    assert content["requirement"]["status"] == "published"
    assert float(content["requirement"]["numeric_value"]) == 7.0
    assert content["evidence"]["review_note"] == (
        "Confirmed on the 2027 admissions page"
    )

    repeat = client.post(
        f"{REQUIREMENTS_URL}/evidence/{conflict.evidence.id}/accept",
        headers=superuser_token_headers,
        json={"note": "again"},
    )
    assert repeat.status_code == 409


def test_superuser_rejects_a_conflict(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    program = create_random_program(db)
    ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="6.5")
    )
    conflict = ingest_evidence(
        session=db, program_id=program.id, evidence_in=ielts_evidence(overall="7.0")
    )

    response = client.post(
        f"{REQUIREMENTS_URL}/evidence/{conflict.evidence.id}/reject",
        headers=superuser_token_headers,
        json={"note": "Not an official source"},
    )

    assert response.status_code == 200
    content = response.json()
    assert content["decision"] == "evidence_rejected"
    assert content["requirement"]["status"] == "published"
    assert float(content["requirement"]["numeric_value"]) == 6.5
    assert content["evidence"]["status"] == "rejected"


def test_reviewing_unknown_evidence_returns_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    response = client.post(
        f"{REQUIREMENTS_URL}/evidence/{uuid.uuid4()}/accept",
        headers=superuser_token_headers,
        json={},
    )
    assert response.status_code == 404
