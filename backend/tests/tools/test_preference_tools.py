import pytest
from sqlmodel import Session, col, select

from app.harness import (
    ExecutionContext,
    PermissionLevel,
    PolicyOutcome,
    ToolErrorCode,
    ToolExecutionError,
    ToolRegistry,
    decide,
    validate_tool_call,
)
from app.modules.preferences import PreferenceChange, PreferenceStatus, UserPreference
from tests.tools.conftest import make_context, run_tool
from tests.utils.user import create_random_user


def _remember(
    registry: ToolRegistry,
    ctx: object,
    *,
    value: str,
    raw_text: str,
    change_kind: str,
    key: str = "campus_environment",
) -> object:
    return run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="remember_user_preference",
        arguments={
            "preference_key": key,
            "value": value,
            "raw_text": raw_text,
            "change_kind": change_kind,
        },
    )


def test_a_declared_replacement_supersedes_the_old_preference(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    ctx = make_context(db, user)
    first = _remember(
        registry,
        ctx,
        value="学校必须有湖，也希望靠海",
        raw_text="以后只申请有湖有海的学校",
        change_kind="new",
    )
    second = _remember(
        registry,
        ctx,
        value="学校必须有湖，海不是必要条件",
        raw_text="有湖就行，海可以不要",
        change_kind="replace",
    )

    assert first.value == "学校必须有湖，也希望靠海"
    assert second.value == "学校必须有湖，海不是必要条件"
    active = run_tool(registry=registry, ctx=ctx, tool_name="list_user_preferences")
    assert active.count == 1
    assert active.data[0].value == second.value

    history = list(
        db.exec(
            select(UserPreference)
            .where(col(UserPreference.user_id) == user.id)
            .order_by(col(UserPreference.created_at))
        ).all()
    )
    assert [row.status for row in history] == [
        PreferenceStatus.SUPERSEDED,
        PreferenceStatus.ACTIVE,
    ]
    # 历史链要说清每一步是哪种变更，而不是只留下两段文本让人猜。
    assert [row.change_kind for row in history] == [
        PreferenceChange.NEW,
        PreferenceChange.REPLACE,
    ]
    assert history[1].supersedes_id == history[0].id
    assert history[1].raw_text == "有湖就行，海可以不要"


def test_declaring_new_on_an_occupied_slot_is_refused(
    db: Session, registry: ToolRegistry
) -> None:
    """模型以为自己在新增、其实会顶掉旧约束——这是必须挡住的那一种错。"""
    user = create_random_user(db)
    ctx = make_context(db, user)
    _remember(
        registry,
        ctx,
        value="学校必须有湖，也希望靠海",
        raw_text="以后只申请有湖有海的学校",
        change_kind="new",
    )

    with pytest.raises(ToolExecutionError) as error:
        _remember(
            registry,
            ctx,
            value="学校必须有湖",
            raw_text="有湖就行",
            change_kind="new",
        )

    assert error.value.code is ToolErrorCode.CONFLICT
    assert "replace" in error.value.message
    active = run_tool(registry=registry, ctx=ctx, tool_name="list_user_preferences")
    assert active.data[0].value == "学校必须有湖，也希望靠海"


def test_declaring_replace_on_an_empty_slot_is_refused(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    ctx = make_context(db, user)

    with pytest.raises(ToolExecutionError) as error:
        _remember(
            registry,
            ctx,
            value="学校必须有湖",
            raw_text="有湖就行",
            change_kind="replace",
        )

    assert error.value.code is ToolErrorCode.CONFLICT
    assert "new" in error.value.message


def test_a_refinement_keeps_the_chain_but_needs_no_confirmation(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    ctx = make_context(db, user)
    _remember(
        registry,
        ctx,
        value="学校必须有湖",
        raw_text="以后只申请有湖的学校",
        change_kind="new",
    )
    refined = _remember(
        registry,
        ctx,
        value="学校必须有湖，而且希望树多",
        raw_text="再补一条，树要多",
        change_kind="refine",
    )

    assert refined.change_kind is PreferenceChange.REFINE
    rows = list(
        db.exec(
            select(UserPreference).where(col(UserPreference.user_id) == user.id)
        ).all()
    )
    assert len(rows) == 2


def test_restating_the_same_value_does_not_grow_the_history(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    ctx = make_context(db, user)
    _remember(registry, ctx, value="必须有湖", raw_text="只看有湖的", change_kind="new")
    _remember(
        registry,
        ctx,
        value="必须有湖",
        raw_text="再说一次，只看有湖的",
        change_kind="refine",
    )

    rows = list(
        db.exec(
            select(UserPreference).where(col(UserPreference.user_id) == user.id)
        ).all()
    )
    assert len(rows) == 1


def test_replacing_a_preference_requires_human_confirmation(
    db: Session, registry: ToolRegistry
) -> None:
    """不静默覆盖：replace 会被权限层停在人工确认上。"""
    user = create_random_user(db)
    execution = ExecutionContext(user_id=user.id, is_superuser=user.is_superuser)

    replace_call = validate_tool_call(
        registry=registry,
        tool_name="remember_user_preference",
        raw_arguments={
            "preference_key": "campus_environment",
            "value": "必须有湖",
            "raw_text": "有湖就行",
            "change_kind": "replace",
        },
        call_id="call-1",
    )
    new_call = validate_tool_call(
        registry=registry,
        tool_name="remember_user_preference",
        raw_arguments={
            "preference_key": "campus_environment",
            "value": "必须有湖",
            "raw_text": "有湖就行",
            "change_kind": "new",
        },
        call_id="call-2",
    )

    replace_decision = decide(context=execution, call=replace_call)
    new_decision = decide(context=execution, call=new_call)

    assert replace_decision.permission_level is PermissionLevel.HIGH_RISK_WRITE
    assert replace_decision.outcome is PolicyOutcome.REQUIRE_HUMAN_CONFIRMATION
    assert new_decision.permission_level is PermissionLevel.LOW_RISK_WRITE
    assert new_decision.outcome is PolicyOutcome.ALLOW


def test_forgetting_a_preference_requires_human_confirmation(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    call = validate_tool_call(
        registry=registry,
        tool_name="forget_user_preference",
        raw_arguments={"preference_key": "campus_environment"},
        call_id="call-1",
    )

    decision = decide(
        context=ExecutionContext(user_id=user.id, is_superuser=user.is_superuser),
        call=call,
    )

    assert decision.outcome is PolicyOutcome.REQUIRE_HUMAN_CONFIRMATION


def test_forgetting_a_preference_keeps_an_audit_record(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    ctx = make_context(db, user)
    _remember(
        registry,
        ctx,
        value="必须有湖",
        raw_text="以后只看有湖的学校",
        change_kind="new",
    )
    removed = run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="forget_user_preference",
        arguments={"preference_key": "campus_environment"},
    )

    assert removed.preference_key == "campus_environment"
    assert (
        run_tool(registry=registry, ctx=ctx, tool_name="list_user_preferences").count
        == 0
    )
    row = db.exec(
        select(UserPreference).where(col(UserPreference.user_id) == user.id)
    ).one()
    assert row.status is PreferenceStatus.RETRACTED
    # 撤销不删行：以后要解释"这条约束为什么不在了"，得能翻到它。
    assert row.raw_text == "以后只看有湖的学校"


def test_forgetting_an_unknown_preference_is_a_structured_error(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    with pytest.raises(ToolExecutionError) as error:
        run_tool(
            registry=registry,
            ctx=make_context(db, user),
            tool_name="forget_user_preference",
            arguments={"preference_key": "campus_environment"},
        )
    assert error.value.code is ToolErrorCode.NOT_FOUND


def test_preferences_are_isolated_by_user(db: Session, registry: ToolRegistry) -> None:
    owner = create_random_user(db)
    intruder = create_random_user(db)
    _remember(
        registry,
        make_context(db, owner),
        key="school_type",
        value="只考虑公立大学",
        raw_text="以后只考虑公立大学",
        change_kind="new",
    )

    result = run_tool(
        registry=registry,
        ctx=make_context(db, intruder),
        tool_name="list_user_preferences",
    )
    assert result.count == 0


def test_the_same_slot_is_independent_per_user(
    db: Session, registry: ToolRegistry
) -> None:
    """槽位唯一性是按用户算的，别人占了不影响我第一次记录。"""
    owner = create_random_user(db)
    other = create_random_user(db)
    _remember(
        registry,
        make_context(db, owner),
        value="必须有湖",
        raw_text="只看有湖的",
        change_kind="new",
    )

    result = _remember(
        registry,
        make_context(db, other),
        value="必须靠海",
        raw_text="只看靠海的",
        change_kind="new",
    )
    assert result.value == "必须靠海"
