from pydantic import BaseModel, ConfigDict, Field

from app.harness import (
    PermissionLevel,
    ToolContext,
    ToolDefinition,
    ToolErrorCode,
    ToolExecutionError,
)
from app.modules import preferences
from app.modules.preferences import PreferenceChange


class ListPreferencesInput(BaseModel):
    pass


class RememberPreferenceInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    preference_key: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="稳定的英文偏好槽位，例如 campus_environment 或 school_type",
    )
    value: str = Field(
        min_length=1,
        max_length=1000,
        description="供后续决策使用的当前偏好，不包含已经取消的约束",
    )
    raw_text: str = Field(
        min_length=1,
        max_length=2000,
        description="触发本次记忆更新的用户原话",
    )
    change_kind: PreferenceChange = Field(
        description=(
            "这次变更的类型：new=该槽位第一次记录；refine=在旧值上补充或收紧，"
            "旧约束继续成立；replace=推翻旧值。声明会和数据库里的实际存量核对，"
            "对不上会被拒绝并要求重新判断。"
        ),
    )


class ForgetPreferenceInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    preference_key: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )


def _public(row: preferences.UserPreference) -> preferences.PreferencePublic:
    return preferences.PreferencePublic.model_validate(row)


def list_user_preferences(ctx: ToolContext, payload: ListPreferencesInput) -> BaseModel:
    del payload
    rows = preferences.list_active_preferences(session=ctx.session, user_id=ctx.user_id)
    return preferences.PreferencesPublic(
        data=[_public(row) for row in rows], count=len(rows)
    )


def remember_user_preference(
    ctx: ToolContext, payload: RememberPreferenceInput
) -> BaseModel:
    try:
        row = preferences.remember_preference(
            session=ctx.session,
            user_id=ctx.user_id,
            preference_key=payload.preference_key,
            value=payload.value,
            raw_text=payload.raw_text,
            change_kind=payload.change_kind,
        )
    except preferences.PreferenceChangeMismatchError as error:
        # 让模型带着实际存量重新判断，而不是替它猜一个意图。
        raise ToolExecutionError(ToolErrorCode.CONFLICT, str(error)) from error
    except preferences.PreferenceUserNotFoundError as error:
        raise ToolExecutionError(ToolErrorCode.NOT_FOUND, str(error)) from error
    return _public(row)


def forget_user_preference(
    ctx: ToolContext, payload: ForgetPreferenceInput
) -> BaseModel:
    try:
        row = preferences.forget_preference(
            session=ctx.session,
            user_id=ctx.user_id,
            preference_key=payload.preference_key,
        )
    except preferences.PreferenceNotFoundError as error:
        raise ToolExecutionError(ToolErrorCode.NOT_FOUND, str(error)) from error
    return _public(row)


def escalate_remember_preference(payload: BaseModel) -> PermissionLevel:
    """推翻一条已生效的长期约束要用户点头，新增和细化不打扰他。

    这是"不静默覆盖"落到代码里的地方：REPLACE 走高风险分支，权限层会把它停在
    人工确认上；用户拒绝时旧值原样留着。
    """
    assert isinstance(payload, RememberPreferenceInput)
    if payload.change_kind is PreferenceChange.REPLACE:
        return PermissionLevel.HIGH_RISK_WRITE
    return PermissionLevel.LOW_RISK_WRITE


LIST_USER_PREFERENCES = ToolDefinition(
    name="list_user_preferences",
    description=(
        "读取当前用户已经确认、会跨会话生效的长期偏好。不确定某个槽位上已经"
        "记过什么时，先用它看一眼，再决定这次是 new、refine 还是 replace。"
    ),
    input_model=ListPreferencesInput,
    output_model=preferences.PreferencesPublic,
    permission_level=PermissionLevel.READ,
    handler=list_user_preferences,
)

REMEMBER_USER_PREFERENCE = ToolDefinition(
    name="remember_user_preference",
    description=(
        "保存一条跨会话长期偏好。只有用户明确表达“以后、一直、记住”等持久意图时"
        "才调用；“这次、当前这轮”的条件不得写入。必须声明 change_kind："
        "replace 会推翻该槽位的旧约束并需要用户确认，new 和 refine 不会。"
        "含义不明确时先询问用户，不要自行合并。"
    ),
    input_model=RememberPreferenceInput,
    output_model=preferences.PreferencePublic,
    permission_level=PermissionLevel.LOW_RISK_WRITE,
    handler=remember_user_preference,
    escalate=escalate_remember_preference,
)

FORGET_USER_PREFERENCE = ToolDefinition(
    name="forget_user_preference",
    description=(
        "撤销一条已经保存的长期偏好，需要用户确认。用户只是在本轮放宽条件时"
        "不得调用；只想改写而不是取消时用 remember_user_preference 的 replace。"
    ),
    input_model=ForgetPreferenceInput,
    output_model=preferences.PreferencePublic,
    # 撤销一条已生效的长期约束是破坏性的，和 replace 同级。
    permission_level=PermissionLevel.HIGH_RISK_WRITE,
    handler=forget_user_preference,
)
