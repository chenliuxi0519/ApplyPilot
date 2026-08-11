import uuid

import pytest
from sqlmodel import Session, col, select

from app.agent import (
    AgentState,
    AgentStatus,
    Budget,
    InMemoryRunRecorder,
    RunAlreadyStartedError,
)
from app.agent.trace import TraceEventType
from app.harness import ToolRegistry
from app.modules.applications.models import Application, ApplicationStatus
from tests.agent.conftest import (
    call,
    make_loop,
    refusal_response,
    text_response,
    tool_response,
)
from tests.utils.application import (
    complete_required_tasks,
    create_application_for,
    move_to,
)
from tests.utils.program import create_random_program, create_random_university
from tests.utils.user import create_random_user


def _run(db: Session, registry: ToolRegistry, script, user=None, budget=None):
    recorder = InMemoryRunRecorder()
    owner = user or create_random_user(db)
    loop, model = make_loop(
        db=db,
        user=owner,
        script=script,
        registry=registry,
        budget=budget,
        recorder=recorder,
    )
    state = loop.run(AgentState.new(user_id=owner.id), "do the thing")
    return loop, model, state, recorder, owner


def test_a_run_is_opened_and_closed(db: Session, registry: ToolRegistry) -> None:
    _, _, state, recorder, _ = _run(db, registry, [text_response("done")])

    assert recorder.started == [state.run_id]
    assert recorder.finished == [(state.run_id, AgentStatus.COMPLETED.value)]


def test_failed_run_is_recorded_as_failed(db: Session, registry: ToolRegistry) -> None:
    _, _, state, recorder, _ = _run(db, registry, [refusal_response()])
    assert recorder.finished == [(state.run_id, AgentStatus.FAILED.value)]


def test_budget_exceeded_run_is_recorded(db: Session, registry: ToolRegistry) -> None:
    university = create_random_university(db)
    create_random_program(db, university=university)
    _, _, state, recorder, _ = _run(
        db,
        registry,
        [tool_response(call("search_programs", {"university": university.short_name}))],
        budget=Budget(max_steps=1, max_tool_calls=10),
    )
    assert recorder.finished == [(state.run_id, AgentStatus.BUDGET_EXCEEDED.value)]


def test_a_waiting_run_is_recorded_while_it_waits(
    db: Session, registry: ToolRegistry
) -> None:
    user, application, _ = create_application_for(db)
    recorder = InMemoryRunRecorder()
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
                    call_id="toolu_1",
                )
            )
        ],
        registry=registry,
        recorder=recorder,
    )
    state = loop.run(AgentState.new(user_id=user.id), "drop it")

    assert state.status is AgentStatus.WAITING_CONFIRMATION
    assert recorder.finished == [(state.run_id, AgentStatus.WAITING_CONFIRMATION.value)]


def test_a_state_cannot_be_run_twice(db: Session, registry: ToolRegistry) -> None:
    recorder = InMemoryRunRecorder()
    user = create_random_user(db)
    loop, _ = make_loop(
        db=db,
        user=user,
        script=[text_response("first"), text_response("second")],
        registry=registry,
        recorder=recorder,
    )
    state = loop.run(AgentState.new(user_id=user.id), "first task")

    with pytest.raises(RunAlreadyStartedError):
        loop.run(state, "second task")
    assert len(recorder.started) == 1


def test_a_new_task_gets_a_new_run_and_fresh_counters(
    db: Session, registry: ToolRegistry
) -> None:
    university = create_random_university(db)
    create_random_program(db, university=university)
    user = create_random_user(db)
    recorder = InMemoryRunRecorder()
    loop, _ = make_loop(
        db=db,
        user=user,
        script=[
            tool_response(
                call("search_programs", {"university": university.short_name})
            ),
            text_response("first"),
            text_response("second"),
        ],
        registry=registry,
        recorder=recorder,
    )

    first = loop.run(AgentState.new(user_id=user.id), "task one")

    second = loop.run(
        AgentState.new(user_id=user.id, messages=first.messages), "task two"
    )

    assert first.run_id != second.run_id
    assert first.tool_call_count == 1
    assert second.tool_call_count == 0
    assert second.step_count == 1
    assert recorder.started == [first.run_id, second.run_id]


def test_every_trace_event_is_recorded_in_order(
    db: Session, registry: ToolRegistry
) -> None:
    university = create_random_university(db)
    create_random_program(db, university=university)
    _, _, state, recorder, _ = _run(
        db,
        registry,
        [
            tool_response(
                call("search_programs", {"university": university.short_name})
            ),
            text_response("done"),
        ],
    )

    assert recorder.event_types() == [event.event_type.value for event in state.trace]
    assert recorder.sequences() == list(range(len(state.trace)))


def test_sequence_is_the_trace_index(db: Session, registry: ToolRegistry) -> None:
    _, _, state, recorder, _ = _run(db, registry, [text_response("done")])
    for (run_id, sequence, event), expected in zip(
        recorder.events, state.trace, strict=True
    ):
        assert run_id == state.run_id
        assert state.trace[sequence] is event
        assert event is expected


def test_a_parallel_batch_keeps_its_order(db: Session, registry: ToolRegistry) -> None:
    university = create_random_university(db)
    create_random_program(db, university=university)
    _, _, _, recorder, _ = _run(
        db,
        registry,
        [
            tool_response(
                call("get_user_profile", {}, call_id="c1"),
                call(
                    "search_programs",
                    {"university": university.short_name},
                    call_id="c2",
                ),
            ),
            text_response("done"),
        ],
    )

    tool_ids = [
        event.tool_call_id
        for _, _, event in recorder.events
        if event.event_type is TraceEventType.TOOL_CALL
    ]
    assert tool_ids == ["c1", "c2"]


def test_resume_keeps_the_same_run_and_continues_the_sequence(
    db: Session, registry: ToolRegistry
) -> None:
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

    recorder = InMemoryRunRecorder()
    loop, _ = make_loop(
        db=db,
        user=user,
        script=[
            tool_response(
                call(
                    "update_application_status",
                    {
                        "application_id": str(application.id),
                        "target_status": "submitted",
                        "version": application.version,
                    },
                    call_id="toolu_submit",
                )
            ),
            text_response("Submitted."),
        ],
        registry=registry,
        recorder=recorder,
    )
    state = loop.run(AgentState.new(user_id=user.id), "I submitted it")
    run_id = state.run_id
    events_at_pause = len(recorder.events)

    state = loop.resume_approved(state)

    assert state.run_id == run_id
    assert {rid for rid, _, _ in recorder.events} == {run_id}
    assert recorder.started == [run_id]
    assert recorder.sequences() == list(range(len(recorder.events)))
    assert len(recorder.events) > events_at_pause
    assert TraceEventType.HUMAN_APPROVED.value in recorder.event_types()
    assert recorder.finished[-1] == (run_id, AgentStatus.COMPLETED.value)


def test_a_rejection_is_recorded(db: Session, registry: ToolRegistry) -> None:
    user, application, _ = create_application_for(db)
    recorder = InMemoryRunRecorder()
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
                    call_id="toolu_1",
                )
            ),
            text_response("Left as it was."),
        ],
        registry=registry,
        recorder=recorder,
    )
    state = loop.run(AgentState.new(user_id=user.id), "drop it")
    loop.resume_rejected(state)

    assert TraceEventType.HUMAN_CONFIRMATION_REQUIRED.value in recorder.event_types()
    assert TraceEventType.HUMAN_REJECTED.value in recorder.event_types()
    assert TraceEventType.RUN_RESUMED.value in recorder.event_types()


class _BrokenRecorder:
    def start_run(self, state) -> None:
        raise RuntimeError("recorder is down")

    def record_event(self, run_id, sequence, event) -> None:
        raise RuntimeError("recorder is down")

    def finish_run(self, state) -> None:
        raise RuntimeError("recorder is down")


def test_a_broken_recorder_does_not_undo_a_committed_tool(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    program = create_random_program(db)
    loop, _ = make_loop(
        db=db,
        user=user,
        script=[
            tool_response(
                call(
                    "create_application",
                    {"program_id": str(program.id), "application_cycle": "2026/27"},
                )
            ),
            text_response("Added."),
        ],
        registry=registry,
        recorder=_BrokenRecorder(),
    )
    state = loop.run(AgentState.new(user_id=user.id), "add it")

    assert state.status is AgentStatus.COMPLETED
    assert (
        db.exec(
            select(Application).where(col(Application.user_id) == user.id)
        ).one_or_none()
        is not None
    )


def test_a_broken_recorder_is_counted_rather_than_swallowed(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    loop, _ = make_loop(
        db=db,
        user=user,
        script=[text_response("done")],
        registry=registry,
        recorder=_BrokenRecorder(),
    )
    state = loop.run(AgentState.new(user_id=user.id), "hello")

    assert state.status is AgentStatus.COMPLETED

    assert state.observability_failures == 4
    assert state.last_observability_error == "recorder is down"


def test_the_trace_still_holds_everything_a_recorder_dropped(
    db: Session, registry: ToolRegistry
) -> None:
    user = create_random_user(db)
    loop, _ = make_loop(
        db=db,
        user=user,
        script=[text_response("done")],
        registry=registry,
        recorder=_BrokenRecorder(),
    )
    state = loop.run(AgentState.new(user_id=user.id), "hello")

    assert [event.event_type for event in state.trace] == [
        TraceEventType.MODEL_REQUEST,
        TraceEventType.RUN_FINISHED,
    ]


def test_no_event_escapes_the_recorder() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "app" / "agent" / "loop.py"
    ).read_text(encoding="utf-8")
    assert "state.trace.append" not in source.replace(
        "        state.trace.append(event)", ""
    )


def test_run_ids_are_unique_per_state() -> None:
    user_id = uuid.uuid4()
    assert (
        AgentState.new(user_id=user_id).run_id != AgentState.new(user_id=user_id).run_id
    )
