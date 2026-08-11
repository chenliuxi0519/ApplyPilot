import json

import pytest
from sqlmodel import Session

from app.agent import AgentState, AgentStatus, Budget, ResumeNotPendingError
from app.agent.trace import TraceEventType
from app.harness import ToolErrorCode, ToolRegistry
from app.modules.applications.models import ApplicationStatus
from tests.agent.conftest import call, make_loop, text_response, tool_response
from tests.utils.application import (
    advance_to_submitted,
    complete_required_tasks,
    create_application_for,
    move_to,
)
from tests.utils.program import create_random_program, create_random_university
from tests.utils.user import create_random_user

SECRET = "chain-of-thought-marker-do-not-persist"


def _ready_application(db: Session):
    user, application, _ = create_application_for(db)
    application = move_to(
        db, user=user, application=application, target=ApplicationStatus.PREPARING
    )
    complete_required_tasks(db, user=user, application_id=application.id)
    db.refresh(application)
    application = move_to(
        db,
        user=user,
        application=application,
        target=ApplicationStatus.READY_TO_SUBMIT,
    )
    return user, application


def _submit_call(application, call_id: str = "toolu_submit"):
    return call(
        "update_application_status",
        {
            "application_id": str(application.id),
            "target_status": "submitted",
            "version": application.version,
        },
        call_id=call_id,
    )


def _pause_on_submit(db: Session, registry: ToolRegistry, extra_script=()):
    user, application = _ready_application(db)
    loop, model = make_loop(
        db=db,
        user=user,
        script=[tool_response(_submit_call(application)), *extra_script],
        registry=registry,
    )
    state = loop.run(
        AgentState.new(user_id=user.id), "I submitted it, update the status"
    )
    return loop, model, state, user, application


def test_marking_submitted_pauses_and_changes_nothing(
    db: Session, registry: ToolRegistry
) -> None:
    _, model, state, user, application = _pause_on_submit(db, registry)

    assert state.status is AgentStatus.WAITING_CONFIRMATION
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.tool_name == "update_application_status"
    assert state.pending_batch is not None
    assert state.pending_batch.confirmation_call_ids == {"toolu_submit"}
    assert state.tool_call_count == 0
    assert model.calls == 1

    db.refresh(application)
    assert application.status is ApplicationStatus.READY_TO_SUBMIT
    assert application.submitted_at is None
    assert application.version == 3


def test_pending_batch_holds_only_serializable_data(
    db: Session, registry: ToolRegistry
) -> None:
    _, _, state, _, _ = _pause_on_submit(db, registry)
    assert state.pending_batch is not None

    json.dumps(
        [
            {"id": c.id, "name": c.name, "arguments": c.arguments}
            for c in state.pending_batch.model_calls
        ]
    )


def test_approve_executes_the_original_call_and_updates_the_database(
    db: Session, registry: ToolRegistry
) -> None:
    loop, model, state, _, application = _pause_on_submit(
        db, registry, extra_script=[text_response("Marked as submitted.")]
    )
    calls_before_resume = model.calls

    state = loop.resume_approved(state)

    assert state.status is AgentStatus.COMPLETED
    assert state.final_answer == "Marked as submitted."

    assert model.calls == calls_before_resume + 1

    db.refresh(application)
    assert application.status is ApplicationStatus.SUBMITTED
    assert application.submitted_at is not None

    result_block = model.seen_messages[-1][-1]["content"][0]
    assert result_block["tool_use_id"] == "toolu_submit"
    assert result_block["is_error"] is False
    output = result_block["result"]["output"]
    assert output["previous_status"] == "ready_to_submit"
    assert output["current_status"] == "submitted"
    assert output["program_name"]


def test_approve_counts_the_executed_call(db: Session, registry: ToolRegistry) -> None:
    loop, _, state, _, _ = _pause_on_submit(
        db, registry, extra_script=[text_response("done")]
    )
    assert state.tool_call_count == 0
    state = loop.resume_approved(state)
    assert state.tool_call_count == 1


def test_reject_leaves_the_application_untouched(
    db: Session, registry: ToolRegistry
) -> None:
    loop, model, state, _, application = _pause_on_submit(
        db, registry, extra_script=[text_response("I left it as it was.")]
    )

    state = loop.resume_rejected(state)

    assert state.status is AgentStatus.COMPLETED
    assert state.final_answer == "I left it as it was."

    db.refresh(application)
    assert application.status is ApplicationStatus.READY_TO_SUBMIT
    assert application.submitted_at is None


def test_reject_reports_user_rejected_to_the_model(
    db: Session, registry: ToolRegistry
) -> None:
    loop, model, state, _, _ = _pause_on_submit(
        db, registry, extra_script=[text_response("ok")]
    )
    state = loop.resume_rejected(state)

    result_block = model.seen_messages[-1][-1]["content"][0]
    assert result_block["tool_use_id"] == "toolu_submit"
    assert result_block["is_error"] is True
    assert result_block["result"]["error"]["code"] == ToolErrorCode.USER_REJECTED.value


def test_reject_is_not_a_failure_and_spends_no_tool_budget(
    db: Session, registry: ToolRegistry
) -> None:
    loop, _, state, _, _ = _pause_on_submit(
        db, registry, extra_script=[text_response("ok")]
    )
    state = loop.resume_rejected(state)

    assert state.status is AgentStatus.COMPLETED
    assert state.last_error is None
    assert state.tool_call_count == 0


def test_a_confirmation_cannot_be_resolved_twice(
    db: Session, registry: ToolRegistry
) -> None:
    loop, _, state, _, application = _pause_on_submit(
        db, registry, extra_script=[text_response("done")]
    )
    state = loop.resume_approved(state)
    version_after = application.version

    with pytest.raises(ResumeNotPendingError):
        loop.resume_approved(state)

    db.refresh(application)
    assert application.version == version_after
    assert state.tool_call_count == 1


def test_approve_then_reject_is_refused(db: Session, registry: ToolRegistry) -> None:
    loop, _, state, _, _ = _pause_on_submit(
        db, registry, extra_script=[text_response("done")]
    )
    loop.resume_approved(state)
    with pytest.raises(ResumeNotPendingError):
        loop.resume_rejected(state)


def test_resume_requires_a_waiting_run(db: Session, registry: ToolRegistry) -> None:
    user = create_random_user(db)
    loop, _ = make_loop(
        db=db, user=user, script=[text_response("hello")], registry=registry
    )
    state = loop.run(AgentState.new(user_id=user.id), "hi")
    assert state.status is AgentStatus.COMPLETED

    with pytest.raises(ResumeNotPendingError):
        loop.resume_approved(state)


def test_resume_requires_a_pending_batch(db: Session, registry: ToolRegistry) -> None:
    loop, _, state, _, _ = _pause_on_submit(db, registry)
    state.pending_batch = None

    with pytest.raises(ResumeNotPendingError):
        loop.resume_approved(state)


def test_an_illegal_transition_is_still_refused_after_approval(
    db: Session, registry: ToolRegistry
) -> None:
    user, application, _ = create_application_for(db)
    loop, model = make_loop(
        db=db,
        user=user,
        script=[
            tool_response(_submit_call(application)),
            text_response("That transition is not allowed."),
        ],
        registry=registry,
    )
    state = loop.run(AgentState.new(user_id=user.id), "mark it submitted")
    assert state.status is AgentStatus.WAITING_CONFIRMATION

    state = loop.resume_approved(state)

    result_block = model.seen_messages[-1][-1]["content"][0]
    assert result_block["result"]["error"]["code"] == ToolErrorCode.CONFLICT.value
    db.refresh(application)
    assert application.status is ApplicationStatus.SHORTLISTED


def test_readiness_still_blocks_ready_to_submit(
    db: Session, registry: ToolRegistry
) -> None:
    user, application, _ = create_application_for(db)
    application = move_to(
        db, user=user, application=application, target=ApplicationStatus.PREPARING
    )
    loop, model = make_loop(
        db=db,
        user=user,
        script=[
            tool_response(
                call(
                    "update_application_status",
                    {
                        "application_id": str(application.id),
                        "target_status": "ready_to_submit",
                        "version": application.version,
                    },
                )
            ),
            text_response("You still have tasks to finish."),
        ],
        registry=registry,
    )

    state = loop.run(AgentState.new(user_id=user.id), "mark it ready")

    assert state.status is AgentStatus.COMPLETED
    error = model.seen_messages[-1][-1]["content"][0]["result"]["error"]
    assert error["code"] == ToolErrorCode.DOMAIN_INVALID.value
    assert set(error["details"]["blocking_task_types"]) == {
        "cv",
        "personal_statement",
        "transcript",
        "application_form",
    }
    db.refresh(application)
    assert application.status is ApplicationStatus.PREPARING


def _mixed_batch(db: Session, registry: ToolRegistry, extra_script=()):
    user, application = _ready_application(db)
    university = create_random_university(db)
    create_random_program(db, university=university)
    loop, model = make_loop(
        db=db,
        user=user,
        script=[
            tool_response(
                call(
                    "search_programs",
                    {"university": university.short_name},
                    call_id="toolu_read",
                ),
                _submit_call(application),
            ),
            *extra_script,
        ],
        registry=registry,
    )
    state = loop.run(AgentState.new(user_id=user.id), "look and submit")
    return loop, model, state, application


def test_a_batch_with_one_high_risk_call_pauses_entirely(
    db: Session, registry: ToolRegistry
) -> None:
    _, _, state, application = _mixed_batch(db, registry)

    assert state.status is AgentStatus.WAITING_CONFIRMATION
    assert state.pending_batch is not None
    assert len(state.pending_batch.model_calls) == 2
    assert state.pending_batch.confirmation_call_ids == {"toolu_submit"}

    assert state.tool_call_count == 0


def test_approving_a_batch_runs_every_call_in_one_message(
    db: Session, registry: ToolRegistry
) -> None:
    loop, model, state, application = _mixed_batch(
        db, registry, extra_script=[text_response("Both done.")]
    )
    state = loop.resume_approved(state)

    assert state.status is AgentStatus.COMPLETED
    results = model.seen_messages[-1][-1]["content"]
    assert [block["tool_use_id"] for block in results] == ["toolu_read", "toolu_submit"]
    assert all(block["is_error"] is False for block in results)
    assert state.tool_call_count == 2

    db.refresh(application)
    assert application.status is ApplicationStatus.SUBMITTED


def test_rejecting_a_batch_still_runs_the_low_risk_calls(
    db: Session, registry: ToolRegistry
) -> None:
    loop, model, state, application = _mixed_batch(
        db, registry, extra_script=[text_response("Found them; left the status alone.")]
    )
    state = loop.resume_rejected(state)

    assert state.status is AgentStatus.COMPLETED
    results = model.seen_messages[-1][-1]["content"]
    assert [block["tool_use_id"] for block in results] == ["toolu_read", "toolu_submit"]
    assert results[0]["is_error"] is False
    assert results[1]["is_error"] is True
    assert results[1]["result"]["error"]["code"] == ToolErrorCode.USER_REJECTED.value

    assert state.tool_call_count == 1

    db.refresh(application)
    assert application.status is ApplicationStatus.READY_TO_SUBMIT


def test_resume_inherits_the_original_budget(
    db: Session, registry: ToolRegistry
) -> None:
    user, application = _ready_application(db)
    loop, _ = make_loop(
        db=db,
        user=user,
        script=[
            tool_response(_submit_call(application)),
            text_response("done"),
        ],
        registry=registry,
        budget=Budget(max_steps=2, max_tool_calls=10),
    )
    state = loop.run(AgentState.new(user_id=user.id), "submit it")
    assert state.step_count == 1

    state = loop.resume_approved(state)

    assert state.step_count == 2
    assert state.status is AgentStatus.COMPLETED


def test_resume_does_not_reset_an_exhausted_step_budget(
    db: Session, registry: ToolRegistry
) -> None:
    user, application = _ready_application(db)
    loop, _ = make_loop(
        db=db,
        user=user,
        script=[tool_response(_submit_call(application))],
        registry=registry,
        budget=Budget(max_steps=1, max_tool_calls=10),
    )
    state = loop.run(AgentState.new(user_id=user.id), "submit it")
    state = loop.resume_approved(state)

    assert state.status is AgentStatus.BUDGET_EXCEEDED
    assert state.step_count == 1
    assert state.tool_call_count == 1


def test_trace_records_the_confirmation_and_the_approval(
    db: Session, registry: ToolRegistry
) -> None:
    loop, _, state, _, _ = _pause_on_submit(
        db, registry, extra_script=[text_response("done")]
    )
    assert any(
        event.event_type is TraceEventType.HUMAN_CONFIRMATION_REQUIRED
        for event in state.trace
    )

    state = loop.resume_approved(state)
    types = [event.event_type for event in state.trace]
    assert TraceEventType.HUMAN_APPROVED in types
    assert TraceEventType.RUN_RESUMED in types
    approval = next(
        e for e in state.trace if e.event_type is TraceEventType.HUMAN_APPROVED
    )
    assert approval.tool_call_id == "toolu_submit"
    assert approval.tool_name == "update_application_status"


def test_trace_records_a_rejection(db: Session, registry: ToolRegistry) -> None:
    loop, _, state, _, _ = _pause_on_submit(
        db, registry, extra_script=[text_response("ok")]
    )
    state = loop.resume_rejected(state)
    types = [event.event_type for event in state.trace]

    assert TraceEventType.HUMAN_REJECTED in types
    assert TraceEventType.RUN_RESUMED in types
    rejection = next(e for e in state.trace if e.event_type is TraceEventType.TOOL_CALL)
    assert rejection.error_code is ToolErrorCode.USER_REJECTED


def test_trace_leaks_no_arguments_output_or_model_text(
    db: Session, registry: ToolRegistry
) -> None:
    user, application = _ready_application(db)
    loop, _ = make_loop(
        db=db,
        user=user,
        script=[
            tool_response(_submit_call(application)),
            text_response(SECRET),
        ],
        registry=registry,
    )
    state = loop.run(AgentState.new(user_id=user.id), SECRET)
    state = loop.resume_approved(state)

    serialized = json.dumps(state.trace_dicts())
    assert SECRET not in serialized
    assert str(application.id) not in serialized
    assert "submitted_at" not in serialized
    assert "program_name" not in serialized

    assert "toolu_submit" in serialized
    assert "update_application_status" in serialized


def test_submitted_application_cannot_be_reopened_afterwards(
    db: Session, registry: ToolRegistry
) -> None:
    loop, model, state, user, application = _pause_on_submit(
        db, registry, extra_script=[text_response("Submitted.")]
    )
    loop.resume_approved(state)
    db.refresh(application)
    assert application.status is ApplicationStatus.SUBMITTED

    loop2, model2 = make_loop(
        db=db,
        user=user,
        script=[
            tool_response(
                call(
                    "update_application_status",
                    {
                        "application_id": str(application.id),
                        "target_status": "preparing",
                        "version": application.version,
                    },
                    call_id="toolu_back",
                )
            ),
            text_response("A submitted application cannot go back."),
        ],
        registry=registry,
    )
    state2 = loop2.run(AgentState.new(user_id=user.id), "put it back to preparing")

    assert state2.status is AgentStatus.COMPLETED
    error = model2.seen_messages[-1][-1]["content"][0]["result"]["error"]
    assert error["code"] == ToolErrorCode.CONFLICT.value
    db.refresh(application)
    assert application.status is ApplicationStatus.SUBMITTED


def test_withdraw_also_requires_confirmation(
    db: Session, registry: ToolRegistry
) -> None:
    user, application, _ = create_application_for(db)
    loop, _ = make_loop(
        db=db,
        user=user,
        script=[
            tool_response(
                call(
                    "update_application_status",
                    {
                        "application_id": str(application.id),
                        "target_status": "withdrawn",
                        "version": application.version,
                    },
                    call_id="toolu_withdraw",
                )
            )
        ],
        registry=registry,
    )
    state = loop.run(AgentState.new(user_id=user.id), "drop this one")

    assert state.status is AgentStatus.WAITING_CONFIRMATION
    db.refresh(application)
    assert application.status is ApplicationStatus.SHORTLISTED


def test_offered_requires_confirmation_even_though_the_service_would_not(
    db: Session, registry: ToolRegistry
) -> None:
    user, application, _ = create_application_for(db)
    application = advance_to_submitted(db, user=user, application=application)
    loop, _ = make_loop(
        db=db,
        user=user,
        script=[
            tool_response(
                call(
                    "update_application_status",
                    {
                        "application_id": str(application.id),
                        "target_status": "offered",
                        "version": application.version,
                    },
                    call_id="toolu_offer",
                )
            )
        ],
        registry=registry,
    )
    state = loop.run(AgentState.new(user_id=user.id), "I got in")

    assert state.status is AgentStatus.WAITING_CONFIRMATION
    db.refresh(application)
    assert application.status is ApplicationStatus.SUBMITTED
