import uuid

from sqlmodel import Session, col, select

from app.agent import AgentState, AgentStatus
from app.harness import PolicyOutcome, ToolErrorCode, ToolRegistry
from app.modules.applications.models import Application
from app.modules.profiles.models import UserProfile
from app.modules.programs.models import Region
from tests.agent.conftest import (
    call,
    make_loop,
    refusal_response,
    text_response,
    tool_response,
)
from tests.utils.program import (
    APPLICATION_CYCLE,
    create_random_program,
    create_random_university,
)
from tests.utils.user import create_random_user


def _run(
    db: Session,
    registry: ToolRegistry,
    script,
    user=None,
    budget=None,
    approved_call_ids: frozenset[str] = frozenset(),
):
    owner = user or create_random_user(db)
    loop, model = make_loop(
        db=db,
        user=owner,
        script=script,
        registry=registry,
        budget=budget,
        approved_call_ids=approved_call_ids,
    )
    state = AgentState.new(user_id=owner.id)
    return loop.run(state, "do the thing"), model, owner


def test_final_answer_without_any_tool(db: Session, registry: ToolRegistry) -> None:
    state, model, _ = _run(db, registry, [text_response("Here is the answer.")])

    assert state.status is AgentStatus.COMPLETED
    assert state.final_answer == "Here is the answer."
    assert state.step_count == 1
    assert state.tool_call_count == 0
    assert model.calls == 1


def test_single_tool_call_then_answer(db: Session, registry: ToolRegistry) -> None:
    university = create_random_university(db, region=Region.SINGAPORE)
    create_random_program(db, university=university)

    state, model, _ = _run(
        db,
        registry,
        [
            tool_response(
                call("search_programs", {"university": university.short_name})
            ),
            text_response("I found one program."),
        ],
    )

    assert state.status is AgentStatus.COMPLETED
    assert state.tool_call_count == 1
    assert state.step_count == 2

    assert {tool["name"] for tool in model.seen_tools[0]} == set(registry.names())


def test_two_consecutive_tool_rounds(db: Session, registry: ToolRegistry) -> None:
    program = create_random_program(db)

    state, _, owner = _run(
        db,
        registry,
        [
            tool_response(call("update_user_profile", {"career_goal": "AI engineer"})),
            tool_response(
                call(
                    "create_application",
                    {
                        "program_id": str(program.id),
                        "application_cycle": APPLICATION_CYCLE,
                    },
                    call_id="call-2",
                )
            ),
            text_response("Added to your plan."),
        ],
    )

    assert state.status is AgentStatus.COMPLETED
    assert state.step_count == 3
    assert state.tool_call_count == 2
    assert (
        db.exec(
            select(Application).where(col(Application.user_id) == owner.id)
        ).one_or_none()
        is not None
    )


def test_tool_result_is_fed_back_in_one_message(
    db: Session, registry: ToolRegistry
) -> None:
    university = create_random_university(db)
    create_random_program(db, university=university)

    _, model, _ = _run(
        db,
        registry,
        [
            tool_response(
                call(
                    "search_programs",
                    {"university": university.short_name},
                    call_id="call-abc",
                )
            ),
            text_response("done"),
        ],
    )

    second_turn = model.seen_messages[1]
    results_message = second_turn[-1]
    assert results_message["role"] == "user"
    assert len(results_message["content"]) == 1
    block = results_message["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "call-abc"
    assert block["is_error"] is False
    assert block["result"]["output"]["count"] == 1


def test_parallel_calls_return_one_message_with_every_result(
    db: Session, registry: ToolRegistry
) -> None:
    university = create_random_university(db)
    create_random_program(db, university=university)

    state, model, _ = _run(
        db,
        registry,
        [
            tool_response(
                call("get_user_profile", {}, call_id="call-1"),
                call(
                    "search_programs",
                    {"university": university.short_name},
                    call_id="call-2",
                ),
                call("update_user_profile", {"career_goal": "AI"}, call_id="call-3"),
            ),
            text_response("done"),
        ],
    )

    assert state.tool_call_count == 3
    results_message = model.seen_messages[1][-1]
    assert [block["tool_use_id"] for block in results_message["content"]] == [
        "call-1",
        "call-2",
        "call-3",
    ]


def test_unknown_tool_is_reported_to_the_model(
    db: Session, registry: ToolRegistry
) -> None:
    state, model, _ = _run(
        db,
        registry,
        [
            tool_response(call("teleport", {"to": "NUS"}, call_id="call-x")),
            text_response("That tool does not exist."),
        ],
    )

    assert state.status is AgentStatus.COMPLETED
    block = model.seen_messages[1][-1]["content"][0]
    assert block["is_error"] is True
    assert block["result"]["error"]["code"] == ToolErrorCode.UNKNOWN_TOOL.value


def test_invalid_input_is_reported_to_the_model(
    db: Session, registry: ToolRegistry
) -> None:
    _, model, _ = _run(
        db,
        registry,
        [
            tool_response(
                call("get_program_requirements", {"program_id": "not-a-uuid"})
            ),
            text_response("I sent a malformed id."),
        ],
    )

    block = model.seen_messages[1][-1]["content"][0]
    assert block["result"]["error"]["code"] == ToolErrorCode.INVALID_INPUT.value


def test_the_policy_runs_before_the_domain_rule(
    db: Session, registry: ToolRegistry
) -> None:
    state, model, owner = _run(
        db,
        registry,
        [tool_response(call("update_user_profile", {"gpa_value": "3.5"}))],
    )

    assert state.status is AgentStatus.WAITING_CONFIRMATION
    assert state.tool_call_count == 0
    assert model.calls == 1
    assert (
        db.exec(
            select(UserProfile).where(col(UserProfile.user_id) == owner.id)
        ).one_or_none()
        is None
    )


def test_domain_error_is_reported_to_the_model(
    db: Session, registry: ToolRegistry
) -> None:
    _, model, owner = _run(
        db,
        registry,
        [
            tool_response(
                call("update_user_profile", {"gpa_value": "3.5"}, call_id="approved-1")
            ),
            text_response("I need the GPA scale too."),
        ],
        approved_call_ids=frozenset({"approved-1"}),
    )

    block = model.seen_messages[1][-1]["content"][0]
    assert block["result"]["error"]["code"] == ToolErrorCode.DOMAIN_INVALID.value
    assert (
        db.exec(
            select(UserProfile).where(col(UserProfile.user_id) == owner.id)
        ).one_or_none()
        is None
    )


def test_conflict_from_the_service_is_reported_to_the_model(
    db: Session, registry: ToolRegistry
) -> None:
    program = create_random_program(db)
    arguments = {
        "program_id": str(program.id),
        "application_cycle": APPLICATION_CYCLE,
    }

    _, model, _ = _run(
        db,
        registry,
        [
            tool_response(call("create_application", arguments, call_id="c1")),
            tool_response(call("create_application", arguments, call_id="c2")),
            text_response("It is already in your plan."),
        ],
    )

    second_batch = model.seen_messages[2][-1]["content"][0]
    assert second_batch["result"]["error"]["code"] == ToolErrorCode.CONFLICT.value
    assert second_batch["result"]["error"]["details"]["existing_application_id"]


def test_identity_spoofing_is_rejected_by_the_guard(
    db: Session, registry: ToolRegistry
) -> None:
    _, model, _ = _run(
        db,
        registry,
        [
            tool_response(call("get_user_profile", {"user_id": str(uuid.uuid4())})),
            text_response("I cannot choose whose profile to read."),
        ],
    )

    block = model.seen_messages[1][-1]["content"][0]
    assert block["result"]["error"]["code"] == ToolErrorCode.INVALID_INPUT.value
    assert block["result"]["error"]["details"]["reserved_arguments"] == ["user_id"]


def test_a_run_cannot_reach_another_users_data(
    db: Session, registry: ToolRegistry
) -> None:
    owner = create_random_user(db)
    _run(
        db,
        registry,
        [
            tool_response(call("update_user_profile", {"career_goal": "AI engineer"})),
            text_response("saved"),
        ],
        user=owner,
    )

    _, model, _ = _run(
        db,
        registry,
        [
            tool_response(call("get_user_profile", {})),
            text_response("You have no profile yet."),
        ],
    )
    block = model.seen_messages[1][-1]["content"][0]
    assert block["result"]["error"]["code"] == ToolErrorCode.NOT_FOUND.value


def test_policy_denial_is_fed_back_and_the_run_continues(
    db: Session, registry: ToolRegistry
) -> None:
    from app.harness import PermissionLevel, ToolDefinition
    from tests.harness.conftest import EchoInput, EchoOutput, echo_handler

    registry.register(
        ToolDefinition(
            name="admin_only",
            description="Test-only administrative tool",
            input_model=EchoInput,
            output_model=EchoOutput,
            permission_level=PermissionLevel.ADMIN_WRITE,
            handler=echo_handler,
        )
    )

    state, model, _ = _run(
        db,
        registry,
        [
            tool_response(call("admin_only", {"message": "hi"})),
            text_response("You are not allowed to do that."),
        ],
    )

    assert state.status is AgentStatus.COMPLETED
    block = model.seen_messages[1][-1]["content"][0]
    assert block["result"]["error"]["code"] == ToolErrorCode.PERMISSION_DENIED.value
    assert any(event.policy_outcome is PolicyOutcome.DENY for event in state.trace)


def test_high_risk_write_stops_the_run_for_confirmation(
    db: Session, registry: ToolRegistry
) -> None:
    state, model, owner = _run(
        db,
        registry,
        [
            tool_response(
                call("update_user_profile", {"gpa_value": "3.8", "gpa_scale": "4.0"})
            )
        ],
    )

    assert state.status is AgentStatus.WAITING_CONFIRMATION
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.tool_name == "update_user_profile"
    assert state.pending_confirmation.arguments["gpa_value"] == "3.8"

    assert state.tool_call_count == 0
    assert (
        db.exec(
            select(UserProfile).where(col(UserProfile.user_id) == owner.id)
        ).one_or_none()
        is None
    )

    assert model.calls == 1


def test_confirmation_stops_the_whole_batch(
    db: Session, registry: ToolRegistry
) -> None:
    university = create_random_university(db)
    create_random_program(db, university=university)

    state, _, owner = _run(
        db,
        registry,
        [
            tool_response(
                call(
                    "search_programs",
                    {"university": university.short_name},
                    call_id="call-read",
                ),
                call(
                    "update_user_profile",
                    {"ielts_overall": "7.5"},
                    call_id="call-write",
                ),
            )
        ],
    )

    assert state.status is AgentStatus.WAITING_CONFIRMATION
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.call_id == "call-write"

    assert state.tool_call_count == 0
    assert (
        db.exec(
            select(UserProfile).where(col(UserProfile.user_id) == owner.id)
        ).one_or_none()
        is None
    )


def test_refusal_fails_the_run(db: Session, registry: ToolRegistry) -> None:
    state, _, _ = _run(db, registry, [refusal_response()])

    assert state.status is AgentStatus.FAILED
    assert state.last_error is not None
    assert state.last_error.code is ToolErrorCode.INTERNAL
