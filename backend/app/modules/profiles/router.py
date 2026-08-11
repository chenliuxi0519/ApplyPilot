from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SessionDep
from app.modules.profiles import service
from app.modules.profiles.models import (
    ProfileFieldSource,
    ProfileVerificationStatus,
)
from app.modules.profiles.schemas import UserProfilePublic, UserProfileUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/me", response_model=UserProfilePublic)
def read_profile_me(session: SessionDep, current_user: CurrentUser) -> Any:
    try:
        return service.get_profile_or_raise(
            session=session,
            user_id=current_user.id,
        )
    except service.ProfileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.patch("/me", response_model=UserProfilePublic)
def update_profile_me(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    profile_update: UserProfileUpdate,
) -> Any:
    try:
        return service.update_profile(
            session=session,
            user_id=current_user.id,
            profile_update=profile_update,
            source=ProfileFieldSource.USER_EXPLICIT,
            confidence=Decimal("1.000"),
            verification_status=ProfileVerificationStatus.USER_CONFIRMED,
        )
    except service.ProfileValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except service.ProfileUserNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
