"""崩溃重放不能把同一次写操作执行两遍。"""

import uuid

import pytest
from sqlmodel import Session, col, func, select

from app.harness import (
    ToolContext,
    ToolErrorCode,
    ToolRegistry,
    build_key,
    execute_tool,
    validate_tool_call,
)
from app.harness.idempotency import ToolExecution, ToolExecutionStatus
from app.modules.preferences import PreferenceStatus, UserPreference
from app.tools import build_default_registry
from tests.tools.conftest import make_context
from tests.utils.user import create_random_user


@pytest.fixture
def registry() -> ToolRegistry:
    """盖掉本目录 conftest 里的假 registry：这里要的是真会写库的工具。"""
    return build_default_registry()


REMEMBER_ARGS = {
    "preference_key": "campus_environment",
    "value": "学校必须有湖",
    "raw_text": "以后只申请有湖的学校",
    "change_kind": "new",
}


def _call(registry: ToolRegistry, tool_name: str, arguments: dict, call_id: str):
    return validate_tool_call(
        registry=registry,
        tool_name=tool_name,
        raw_arguments=arguments,
        call_id=call_id,
    )


def _active_preferences(db: Session, user_id: uuid.UUID) -> int:
    return db.exec(
        select(func.count())
        .select_from(UserPreference)
        .where(
            col(UserPreference.user_id) == user_id,
            col(UserPreference.status) == PreferenceStatus.ACTIVE,
        )
    ).one()


def test_replaying_a_write_call_does_not_write_twice(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    ctx = make_context(db, user)
    call = _call(registry, "remember_user_preference", REMEMBER_ARGS, "call-1")
    key = build_key(run_id=str(uuid.uuid4()), call_id=call.call_id)

    first = execute_tool(call=call, ctx=ctx, idempotency_key=key)
    # 同一个 run_id + call_id 再来一次，就是崩溃恢复后的重放。
    second = execute_tool(call=call, ctx=ctx, idempotency_key=key)

    assert first.status == "ok"
    assert second.status == "ok"
    assert second.output is not None
    assert second.output.model_dump(mode="json") == first.output.model_dump(mode="json")

    # 重放没有生出第二条记录，旧值也没有被自己顶掉。
    assert _active_preferences(db, user.id) == 1
    assert (
        db.exec(
            select(func.count())
            .select_from(UserPreference)
            .where(col(UserPreference.user_id) == user.id)
        ).one()
        == 1
    )


def test_a_different_call_id_is_a_different_execution(
    db: Session, registry: ToolRegistry
) -> None:
    """重放看 call_id，不看参数：用户真的说第二次，仍然要写进去。"""
    user = create_random_user(db)
    ctx = make_context(db, user)
    run_id = str(uuid.uuid4())

    first = _call(registry, "remember_user_preference", REMEMBER_ARGS, "call-1")
    execute_tool(
        call=first,
        ctx=ctx,
        idempotency_key=build_key(run_id=run_id, call_id=first.call_id),
    )
    second = _call(
        registry,
        "remember_user_preference",
        REMEMBER_ARGS | {"value": "学校必须有湖，海可以不要", "change_kind": "replace"},
        "call-2",
    )
    execute_tool(
        call=second,
        ctx=ctx,
        idempotency_key=build_key(run_id=run_id, call_id=second.call_id),
    )

    assert _active_preferences(db, user.id) == 1
    active = db.exec(
        select(UserPreference).where(
            col(UserPreference.user_id) == user.id,
            col(UserPreference.status) == PreferenceStatus.ACTIVE,
        )
    ).one()
    assert active.value == "学校必须有湖，海可以不要"


def test_an_interrupted_execution_is_reported_instead_of_retried(
    db: Session, registry: ToolRegistry
) -> None:
    """上次执行到一半就断了，副作用不明——报冲突，不许自动重试。"""
    user = create_random_user(db)
    ctx = make_context(db, user)
    call = _call(registry, "remember_user_preference", REMEMBER_ARGS, "call-1")
    key = build_key(run_id=str(uuid.uuid4()), call_id=call.call_id)

    # 手工制造"抢到了占位，但没跑完"的那一行。
    db.add(
        ToolExecution(user_id=user.id, idempotency_key=key, tool_name=call.tool_name)
    )
    db.commit()

    result = execute_tool(call=call, ctx=ctx, idempotency_key=key)

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code is ToolErrorCode.CONFLICT
    assert _active_preferences(db, user.id) == 0


def test_a_failed_tool_releases_its_claim(db: Session, registry: ToolRegistry) -> None:
    """工具报错说明没改到业务表，占位要放掉，否则后续重试会被误判成状态不明。"""
    user = create_random_user(db)
    ctx = make_context(db, user)
    call = _call(
        registry, "forget_user_preference", {"preference_key": "nothing_here"}, "call-1"
    )
    key = build_key(run_id=str(uuid.uuid4()), call_id=call.call_id)

    result = execute_tool(call=call, ctx=ctx, idempotency_key=key)

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code is ToolErrorCode.NOT_FOUND
    assert (
        db.exec(
            select(ToolExecution).where(col(ToolExecution.idempotency_key) == key)
        ).one_or_none()
        is None
    )


def test_read_only_tools_are_not_recorded(db: Session, registry: ToolRegistry) -> None:
    """只读工具重放没有副作用，不该为它写记录。"""
    user = create_random_user(db)
    ctx: ToolContext = make_context(db, user)
    call = _call(registry, "list_user_preferences", {}, "call-1")
    key = build_key(run_id=str(uuid.uuid4()), call_id=call.call_id)

    result = execute_tool(call=call, ctx=ctx, idempotency_key=key)

    assert result.status == "ok"
    assert (
        db.exec(
            select(ToolExecution).where(col(ToolExecution.idempotency_key) == key)
        ).one_or_none()
        is None
    )


def test_a_completed_record_keeps_the_output(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    ctx = make_context(db, user)
    call = _call(registry, "remember_user_preference", REMEMBER_ARGS, "call-1")
    key = build_key(run_id=str(uuid.uuid4()), call_id=call.call_id)

    execute_tool(call=call, ctx=ctx, idempotency_key=key)

    row = db.exec(
        select(ToolExecution).where(col(ToolExecution.idempotency_key) == key)
    ).one()
    assert row.status == ToolExecutionStatus.SUCCEEDED
    assert row.completed_at is not None
    assert row.output is not None
    assert row.output["value"] == REMEMBER_ARGS["value"]
