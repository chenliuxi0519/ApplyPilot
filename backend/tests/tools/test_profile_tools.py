from decimal import Decimal

import pytest
from sqlmodel import Session, col, select

from app.harness import ToolErrorCode, ToolExecutionError, ToolRegistry
from app.modules.profiles.models import (
    ProfileFieldHistory,
    ProfileFieldSource,
    ProfileVerificationStatus,
    UserProfile,
)
from app.tools.profile import AGENT_CONFIDENCE_PLACEHOLDER
from tests.tools.conftest import make_context, run_tool
from tests.utils.user import create_random_user


def test_update_then_read_own_profile(db: Session, registry: ToolRegistry) -> None:
    user = create_random_user(db)
    ctx = make_context(db, user)

    written = run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="update_user_profile",
        arguments={
            "undergraduate_university": "Shanghai University",
            "career_goal": "AI engineer",
        },
    )
    assert written.undergraduate_university == "Shanghai University"

    read = run_tool(
        registry=registry, ctx=ctx, tool_name="get_user_profile", arguments={}
    )
    assert read.career_goal == "AI engineer"
    assert read.target_regions == []


def test_agent_writes_are_recorded_as_unverified(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    ctx = make_context(db, user)

    run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="update_user_profile",
        arguments={"ielts_overall": "7.0"},
    )

    profile = db.exec(
        select(UserProfile).where(col(UserProfile.user_id) == user.id)
    ).one()
    history = db.exec(
        select(ProfileFieldHistory).where(
            col(ProfileFieldHistory.user_profile_id) == profile.id
        )
    ).all()

    assert len(history) == 1
    assert history[0].source is ProfileFieldSource.AGENT_EXTRACTED
    assert history[0].verification_status is ProfileVerificationStatus.UNVERIFIED

    assert history[0].confidence == AGENT_CONFIDENCE_PLACEHOLDER


def test_missing_profile_is_a_structured_not_found(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    ctx = make_context(db, user)

    with pytest.raises(ToolExecutionError) as error:
        run_tool(registry=registry, ctx=ctx, tool_name="get_user_profile", arguments={})
    assert error.value.code is ToolErrorCode.NOT_FOUND


def test_domain_rule_violation_maps_to_domain_invalid(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    ctx = make_context(db, user)

    with pytest.raises(ToolExecutionError) as error:
        run_tool(
            registry=registry,
            ctx=ctx,
            tool_name="update_user_profile",
            arguments={"gpa_value": "3.5"},
        )
    assert error.value.code is ToolErrorCode.DOMAIN_INVALID
    assert (
        db.exec(
            select(UserProfile).where(col(UserProfile.user_id) == user.id)
        ).one_or_none()
        is None
    )


def test_a_tool_call_cannot_read_another_users_profile(
    db: Session, registry: ToolRegistry
) -> None:
    owner = create_random_user(db)
    intruder = create_random_user(db)
    run_tool(
        registry=registry,
        ctx=make_context(db, owner),
        tool_name="update_user_profile",
        arguments={"career_goal": "AI engineer"},
    )

    with pytest.raises(ToolExecutionError) as error:
        run_tool(
            registry=registry,
            ctx=make_context(db, intruder),
            tool_name="get_user_profile",
            arguments={},
        )
    assert error.value.code is ToolErrorCode.NOT_FOUND


def test_a_tool_call_cannot_write_to_another_users_profile(
    db: Session, registry: ToolRegistry
) -> None:
    owner = create_random_user(db)
    intruder = create_random_user(db)
    run_tool(
        registry=registry,
        ctx=make_context(db, owner),
        tool_name="update_user_profile",
        arguments={"career_goal": "AI engineer"},
    )

    run_tool(
        registry=registry,
        ctx=make_context(db, intruder),
        tool_name="update_user_profile",
        arguments={"career_goal": "hijacked"},
    )

    owner_profile = db.exec(
        select(UserProfile).where(col(UserProfile.user_id) == owner.id)
    ).one()
    intruder_profile = db.exec(
        select(UserProfile).where(col(UserProfile.user_id) == intruder.id)
    ).one()

    assert owner_profile.career_goal == "AI engineer"
    assert intruder_profile.career_goal == "hijacked"
    assert owner_profile.id != intruder_profile.id


def test_partial_update_leaves_other_fields_alone(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    ctx = make_context(db, user)
    run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="update_user_profile",
        arguments={"gpa_value": "3.4", "gpa_scale": "4.0"},
    )
    updated = run_tool(
        registry=registry,
        ctx=ctx,
        tool_name="update_user_profile",
        arguments={"career_goal": "AI engineer"},
    )
    assert updated.gpa_value == Decimal("3.40")
    assert updated.career_goal == "AI engineer"
