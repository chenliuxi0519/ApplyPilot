from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.modules.profiles.models import ProfileFieldHistory


def test_get_profile_me_returns_not_found_before_creation(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/profile/me",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404


def test_patch_profile_me_creates_confirmed_history(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    response = client.patch(
        f"{settings.API_V1_STR}/profile/me",
        headers=normal_user_token_headers,
        json={"budget_cny": 200000, "target_fields": ["Computer Science"]},
    )
    assert response.status_code == 200
    profile = response.json()
    assert profile["budget_cny"] == 200000

    history = db.exec(
        select(ProfileFieldHistory).where(
            ProfileFieldHistory.user_profile_id == profile["id"]
        )
    ).all()
    assert len(history) == 2
    assert all(row.source.value == "user_explicit" for row in history)
    assert all(row.verification_status.value == "user_confirmed" for row in history)
    assert all(str(row.confidence) == "1.000" for row in history)


def test_patch_profile_me_rejects_invalid_budget(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    response = client.patch(
        f"{settings.API_V1_STR}/profile/me",
        headers=normal_user_token_headers,
        json={"budget_cny": -1},
    )
    assert response.status_code == 422
