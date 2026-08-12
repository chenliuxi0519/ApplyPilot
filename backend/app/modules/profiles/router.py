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


@router.get("/me", response_model=UserProfilePublic | None)
def read_profile_me(session: SessionDep, current_user: CurrentUser) -> Any:
    """尚未建档时返回 null，而不是 404。

    每个新用户在填写任何信息之前都处于这个状态，它是正常的空档案，不是错误；
    用 404 表示会让前端把常规状态当成失败路径处理。
    """
    return service.get_profile(session=session, user_id=current_user.id)


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
