import uuid
from decimal import Decimal

from app.harness import (
    ExecutionContext,
    PermissionLevel,
    PolicyOutcome,
    decide,
    validate_tool_call,
)
from app.modules.profiles.schemas import UserProfileUpdate
from app.tools import build_default_registry
from tests.harness.conftest import exploding_handler, make_call, make_definition


def _profile_call(call_id: str, **fields: object) -> object:
    registry = build_default_registry()
    return validate_tool_call(
        registry=registry,
        tool_name="update_user_profile",
        raw_arguments=fields,
        call_id=call_id,
    )


def test_read_is_allowed(context: ExecutionContext) -> None:
    call = make_call(make_definition(permission_level=PermissionLevel.READ))
    decision = decide(context=context, call=call)
    assert decision.outcome is PolicyOutcome.ALLOW
    assert decision.permission_level is PermissionLevel.READ


def test_low_risk_write_is_allowed(context: ExecutionContext) -> None:
    call = make_call(make_definition(permission_level=PermissionLevel.LOW_RISK_WRITE))
    assert decide(context=context, call=call).outcome is PolicyOutcome.ALLOW


def test_high_risk_write_requires_confirmation(
    context: ExecutionContext,
) -> None:
    call = make_call(make_definition(permission_level=PermissionLevel.HIGH_RISK_WRITE))
    decision = decide(context=context, call=call)
    assert decision.outcome is PolicyOutcome.REQUIRE_HUMAN_CONFIRMATION
    assert decision.permission_level is PermissionLevel.HIGH_RISK_WRITE


def test_approved_high_risk_write_is_allowed() -> None:
    call = make_call(
        make_definition(permission_level=PermissionLevel.HIGH_RISK_WRITE),
        call_id="call-42",
    )
    context = ExecutionContext(
        user_id=uuid.uuid4(), approved_call_ids=frozenset({"call-42"})
    )
    assert decide(context=context, call=call).outcome is PolicyOutcome.ALLOW


def test_approval_does_not_transfer_to_another_call() -> None:
    call = make_call(
        make_definition(permission_level=PermissionLevel.HIGH_RISK_WRITE),
        call_id="call-99",
    )
    context = ExecutionContext(
        user_id=uuid.uuid4(), approved_call_ids=frozenset({"call-42"})
    )
    assert (
        decide(context=context, call=call).outcome
        is PolicyOutcome.REQUIRE_HUMAN_CONFIRMATION
    )


def test_admin_write_is_denied_to_a_normal_user(
    context: ExecutionContext,
) -> None:
    call = make_call(make_definition(permission_level=PermissionLevel.ADMIN_WRITE))
    decision = decide(context=context, call=call)
    assert decision.outcome is PolicyOutcome.DENY
    assert decision.permission_level is PermissionLevel.ADMIN_WRITE


def test_admin_write_is_allowed_for_a_superuser() -> None:
    call = make_call(make_definition(permission_level=PermissionLevel.ADMIN_WRITE))
    context = ExecutionContext(user_id=uuid.uuid4(), is_superuser=True)
    assert decide(context=context, call=call).outcome is PolicyOutcome.ALLOW


def test_superuser_still_confirms_a_high_risk_write() -> None:
    call = make_call(make_definition(permission_level=PermissionLevel.HIGH_RISK_WRITE))
    context = ExecutionContext(user_id=uuid.uuid4(), is_superuser=True)
    assert (
        decide(context=context, call=call).outcome
        is PolicyOutcome.REQUIRE_HUMAN_CONFIRMATION
    )


def test_profile_preference_update_stays_low_risk(
    context: ExecutionContext,
) -> None:
    call = _profile_call("call-1", career_goal="AI engineer")
    decision = decide(context=context, call=call)  # type: ignore[arg-type]
    assert decision.outcome is PolicyOutcome.ALLOW
    assert decision.permission_level is PermissionLevel.LOW_RISK_WRITE


def test_profile_graded_result_update_escalates(
    context: ExecutionContext,
) -> None:
    call = _profile_call("call-1", ielts_overall="7.0")
    decision = decide(context=context, call=call)  # type: ignore[arg-type]
    assert decision.outcome is PolicyOutcome.REQUIRE_HUMAN_CONFIRMATION
    assert decision.permission_level is PermissionLevel.HIGH_RISK_WRITE


def test_escalation_triggers_when_a_critical_field_is_mixed_in(
    context: ExecutionContext,
) -> None:
    call = _profile_call(
        "call-1", career_goal="AI engineer", gpa_value="3.5", gpa_scale="4.0"
    )
    decision = decide(context=context, call=call)  # type: ignore[arg-type]
    assert decision.outcome is PolicyOutcome.REQUIRE_HUMAN_CONFIRMATION


def test_escalation_cannot_lower_the_declared_level(
    context: ExecutionContext,
) -> None:
    call = make_call(
        make_definition(
            permission_level=PermissionLevel.HIGH_RISK_WRITE,
            escalate=lambda payload: PermissionLevel.READ,
        )
    )
    decision = decide(context=context, call=call)
    assert decision.permission_level is PermissionLevel.HIGH_RISK_WRITE


def test_policy_never_executes_the_handler(context: ExecutionContext) -> None:
    call = make_call(
        make_definition(
            permission_level=PermissionLevel.ADMIN_WRITE,
            handler=exploding_handler,
        )
    )
    decide(context=context, call=call)


def test_escalation_is_computed_from_declared_fields_only() -> None:

    payload = UserProfileUpdate(career_goal="AI engineer")
    assert payload.gpa_value is None
    assert "gpa_value" not in payload.model_fields_set
    payload_with_gpa = UserProfileUpdate(
        gpa_value=Decimal("3.5"), gpa_scale=Decimal("4.0")
    )
    assert "gpa_value" in payload_with_gpa.model_fields_set
