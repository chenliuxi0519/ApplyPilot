from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlmodel import SQLModel

from app.harness import (
    PermissionLevel,
    ToolContext,
    ToolDefinition,
    ToolErrorCode,
    ToolExecutionError,
)
from app.modules.profiles import service as profile_service
from app.modules.profiles.models import (
    ProfileFieldSource,
    ProfileVerificationStatus,
    UserProfile,
)
from app.modules.profiles.schemas import UserProfileUpdate

CRITICAL_PROFILE_FIELDS = frozenset({"gpa_value", "gpa_scale", "ielts_overall"})


AGENT_CONFIDENCE_PLACEHOLDER = Decimal("1.000")


class GetUserProfileInput(SQLModel):
    pass


class UserProfileOutput(SQLModel):
    undergraduate_university: str | None
    undergraduate_major: str | None
    gpa_value: Decimal | None
    gpa_scale: Decimal | None
    ielts_overall: Decimal | None
    budget_cny: int | None
    target_regions: list[str]
    target_fields: list[str]
    career_goal: str | None
    updated_at: datetime


def _to_output(profile: UserProfile) -> UserProfileOutput:
    return UserProfileOutput.model_validate(profile)


def get_user_profile(ctx: ToolContext, payload: GetUserProfileInput) -> BaseModel:
    del payload
    try:
        profile = profile_service.get_profile_or_raise(
            session=ctx.session, user_id=ctx.user_id
        )
    except profile_service.ProfileNotFoundError as error:
        raise ToolExecutionError(
            ToolErrorCode.NOT_FOUND,
            "当前用户还没有个人档案",
        ) from error
    return _to_output(profile)


def update_user_profile(ctx: ToolContext, payload: UserProfileUpdate) -> BaseModel:
    try:
        profile = profile_service.update_profile(
            session=ctx.session,
            user_id=ctx.user_id,
            profile_update=payload,
            source=ProfileFieldSource.AGENT_EXTRACTED,
            verification_status=ProfileVerificationStatus.UNVERIFIED,
            confidence=AGENT_CONFIDENCE_PLACEHOLDER,
        )
    except profile_service.ProfileValidationError as error:
        raise ToolExecutionError(ToolErrorCode.DOMAIN_INVALID, str(error)) from error
    except profile_service.ProfileUserNotFoundError as error:
        raise ToolExecutionError(ToolErrorCode.NOT_FOUND, str(error)) from error
    return _to_output(profile)


def escalate_profile_update(payload: BaseModel) -> PermissionLevel:
    if CRITICAL_PROFILE_FIELDS & payload.model_fields_set:
        return PermissionLevel.HIGH_RISK_WRITE
    return PermissionLevel.LOW_RISK_WRITE


GET_USER_PROFILE = ToolDefinition(
    name="get_user_profile",
    description=(
        "读取当前用户的长期档案，包括教育背景、GPA、语言成绩、预算、"
        "目标地区和申请方向。"
    ),
    input_model=GetUserProfileInput,
    output_model=UserProfileOutput,
    permission_level=PermissionLevel.READ,
    handler=get_user_profile,
)

UPDATE_USER_PROFILE = ToolDefinition(
    name="update_user_profile",
    description=(
        "创建或更新当前用户的个人档案，只修改本次提供的字段。Agent 写入的"
        "内容在用户确认前标记为未验证。"
    ),
    input_model=UserProfileUpdate,
    output_model=UserProfileOutput,
    permission_level=PermissionLevel.LOW_RISK_WRITE,
    handler=update_user_profile,
    escalate=escalate_profile_update,
)
