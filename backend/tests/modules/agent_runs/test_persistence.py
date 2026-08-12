import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.agent.state import AgentState, AgentStatus
from app.agent.trace import TraceEvent, TraceEventType
from app.core.db import engine
from app.harness import PolicyOutcome, ToolError, ToolErrorCode
from app.modules.agent_runs import service
from app.modules.agent_runs.metrics import compute_metrics
from app.modules.agent_runs.models import AgentRun, AgentRunEvent
from app.modules.agent_runs.recorder import PostgresRunRecorder
from tests.utils.user import create_random_user

FORBIDDEN_COLUMN_HINTS = (
    "argument",
    "output",
    "payload",
    "input",
    "thinking",
    "reasoning",
    "prompt",
    "message",
    "content",
    "text",
)


def _recorder(**kwargs) -> PostgresRunRecorder:
    return PostgresRunRecorder(engine, **kwargs)


def _state(user_id: uuid.UUID) -> AgentState:
    return AgentState.new(user_id=user_id)


def _model_event(step: int = 1) -> TraceEvent:
    return TraceEvent(
        step=step,
        event_type=TraceEventType.MODEL_REQUEST,
        latency_ms=12,
        produced_tool_calls=1,
    )


def _tool_event(status: str = "ok", latency_ms: int = 30) -> TraceEvent:
    return TraceEvent(
        step=1,
        event_type=TraceEventType.TOOL_CALL,
        latency_ms=latency_ms,
        tool_name="search_programs",
        tool_call_id="toolu_1",
        policy_outcome=PolicyOutcome.ALLOW,
        tool_result_status=status,  # type: ignore[arg-type]
        error_code=None if status == "ok" else ToolErrorCode.NOT_FOUND,
    )


def _finished(state: AgentState, status: AgentStatus, **kwargs) -> AgentState:
    state.status = status
    for key, value in kwargs.items():
        setattr(state, key, value)
    return state


def test_the_schema_offers_nowhere_to_store_reasoning(db: Session) -> None:
    rows = db.exec(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_name IN ('agent_run', 'agent_run_event')"
        )  # type: ignore[arg-type]
    ).all()
    assert rows

    offenders = [
        f"{table}.{column}"
        for table, column in rows
        if column != "final_answer"
        and any(hint in column for hint in FORBIDDEN_COLUMN_HINTS)
    ]
    assert offenders == []


def test_sequence_is_unique_within_a_run(db: Session) -> None:
    user = create_random_user(db)
    state = _state(user.id)
    recorder = _recorder()
    recorder.start_run(state)
    recorder.record_event(state.run_id, 0, _model_event())

    with pytest.raises(IntegrityError):
        recorder.record_event(state.run_id, 0, _model_event())


def test_an_open_run_has_no_finish_time(db: Session) -> None:
    user = create_random_user(db)
    db.add(
        AgentRun(
            id=uuid.uuid4(),
            user_id=user.id,
            status=AgentStatus.COMPLETED,
            finished_at=None,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_deleting_the_user_removes_the_history(db: Session) -> None:
    user = create_random_user(db)
    state = _state(user.id)
    recorder = _recorder()
    recorder.start_run(state)
    recorder.record_event(state.run_id, 0, _model_event())
    run_id = state.run_id

    db.delete(user)
    db.commit()
    db.expunge_all()

    assert db.get(AgentRun, run_id) is None
    assert (
        db.exec(select(AgentRunEvent).where(col(AgentRunEvent.run_id) == run_id)).all()
        == []
    )


def test_an_event_round_trips_field_for_field(db: Session) -> None:
    user = create_random_user(db)
    state = _state(user.id)
    recorder = _recorder()
    recorder.start_run(state)
    recorder.record_event(state.run_id, 0, _tool_event())

    db.expire_all()
    stored = db.exec(
        select(AgentRunEvent).where(col(AgentRunEvent.run_id) == state.run_id)
    ).one()
    assert stored.sequence == 0
    assert stored.event_type is TraceEventType.TOOL_CALL
    assert stored.tool_name == "search_programs"
    assert stored.tool_call_id == "toolu_1"
    assert stored.policy_outcome is PolicyOutcome.ALLOW
    assert stored.tool_result_status == "ok"
    assert stored.latency_ms == 30


def test_finishing_records_status_counters_and_answer(db: Session) -> None:
    user = create_random_user(db)
    state = _state(user.id)
    recorder = _recorder()
    recorder.start_run(state)
    recorder.finish_run(
        _finished(
            state,
            AgentStatus.COMPLETED,
            step_count=3,
            tool_call_count=2,
            final_answer="Here you go.",
        )
    )

    db.expire_all()
    run = db.get(AgentRun, state.run_id)
    assert run is not None
    assert run.status is AgentStatus.COMPLETED
    assert run.step_count == 3
    assert run.tool_call_count == 2
    assert run.final_answer == "Here you go."
    assert run.finished_at is not None


def test_a_waiting_run_stays_open(db: Session) -> None:
    user = create_random_user(db)
    state = _state(user.id)
    recorder = _recorder()
    recorder.start_run(state)
    recorder.finish_run(_finished(state, AgentStatus.WAITING_CONFIRMATION))

    db.expire_all()
    run = db.get(AgentRun, state.run_id)
    assert run is not None
    assert run.status is AgentStatus.WAITING_CONFIRMATION
    assert run.finished_at is None


def test_the_final_answer_can_be_withheld(db: Session) -> None:
    user = create_random_user(db)
    state = _state(user.id)
    recorder = _recorder(store_final_answer=False)
    recorder.start_run(state)
    recorder.finish_run(_finished(state, AgentStatus.COMPLETED, final_answer="secret"))

    db.expire_all()
    run = db.get(AgentRun, state.run_id)
    assert run is not None
    assert run.final_answer is None


def test_an_error_code_is_kept(db: Session) -> None:
    user = create_random_user(db)
    state = _state(user.id)
    recorder = _recorder()
    recorder.start_run(state)
    recorder.finish_run(
        _finished(
            state,
            AgentStatus.FAILED,
            last_error=ToolError(code=ToolErrorCode.INTERNAL, message="boom"),
        )
    )

    db.expire_all()
    run = db.get(AgentRun, state.run_id)
    assert run is not None
    assert run.last_error_code is ToolErrorCode.INTERNAL


def test_finishing_an_unknown_run_is_reported(db: Session) -> None:
    user = create_random_user(db)
    with pytest.raises(LookupError):
        _recorder().finish_run(_finished(_state(user.id), AgentStatus.COMPLETED))


def test_the_recorder_keeps_its_own_transaction(db: Session) -> None:
    user = create_random_user(db)
    state = _state(user.id)
    recorder = _recorder()
    recorder.start_run(state)
    recorder.record_event(state.run_id, 0, _model_event())

    db.rollback()
    db.expire_all()

    assert db.get(AgentRun, state.run_id) is not None
    assert (
        len(
            db.exec(
                select(AgentRunEvent).where(col(AgentRunEvent.run_id) == state.run_id)
            ).all()
        )
        == 1
    )


def _recorded_run(db: Session, user, events: list[TraceEvent], status, **kwargs):
    state = _state(user.id)
    recorder = _recorder()
    recorder.start_run(state)
    for sequence, event in enumerate(events):
        recorder.record_event(state.run_id, sequence, event)
    recorder.finish_run(_finished(state, status, **kwargs))
    db.expire_all()
    return state.run_id


def test_replay_returns_events_in_sequence(db: Session) -> None:
    user = create_random_user(db)
    run_id = _recorded_run(
        db,
        user,
        [
            _model_event(),
            _tool_event(),
            TraceEvent(
                step=2,
                event_type=TraceEventType.RUN_FINISHED,
                latency_ms=0,
                final_status="completed",
            ),
        ],
        AgentStatus.COMPLETED,
        step_count=2,
        tool_call_count=1,
    )

    replay = service.build_replay(session=db, user_id=user.id, run_id=run_id)
    assert [event.sequence for event in replay.events] == [0, 1, 2]
    assert [event.event_type for event in replay.events] == [
        TraceEventType.MODEL_REQUEST,
        TraceEventType.TOOL_CALL,
        TraceEventType.RUN_FINISHED,
    ]
    assert replay.metrics.task_success is True


def test_metrics_count_what_happened(db: Session) -> None:
    user = create_random_user(db)
    run_id = _recorded_run(
        db,
        user,
        [
            _model_event(),
            _tool_event(latency_ms=30),
            _tool_event(status="error", latency_ms=12),
            TraceEvent(
                step=1,
                event_type=TraceEventType.HUMAN_CONFIRMATION_REQUIRED,
                latency_ms=0,
                tool_name="update_application_status",
            ),
            TraceEvent(
                step=1,
                event_type=TraceEventType.HUMAN_APPROVED,
                latency_ms=0,
                tool_name="update_application_status",
            ),
        ],
        AgentStatus.COMPLETED,
        step_count=2,
        tool_call_count=2,
    )

    replay = service.build_replay(session=db, user_id=user.id, run_id=run_id)
    metrics = replay.metrics
    assert metrics.task_success is True
    assert metrics.total_steps == 2
    assert metrics.total_tool_calls == 2
    assert metrics.tool_error_count == 1
    assert metrics.confirmation_count == 1
    assert metrics.approval_count == 1
    assert metrics.rejection_count == 0
    assert metrics.total_tool_latency_ms == 42
    assert metrics.run_duration_ms is not None


def test_an_unfinished_run_has_no_duration_and_no_success(db: Session) -> None:
    user = create_random_user(db)
    run_id = _recorded_run(db, user, [_model_event()], AgentStatus.WAITING_CONFIRMATION)
    run = service.get_run(session=db, user_id=user.id, run_id=run_id)
    metrics = compute_metrics(
        run, service.list_run_events(session=db, user_id=user.id, run_id=run_id)
    )

    assert metrics.run_duration_ms is None
    assert metrics.task_success is False


def test_replay_formats_one_line_per_event(db: Session) -> None:
    user = create_random_user(db)
    run_id = _recorded_run(
        db, user, [_model_event(), _tool_event()], AgentStatus.COMPLETED
    )
    lines = service.format_replay(
        service.build_replay(session=db, user_id=user.id, run_id=run_id)
    )

    assert len(lines) == 3
    assert "completed" in lines[0]
    assert "model_request" in lines[1]
    assert "search_programs" in lines[2]


def test_another_users_run_is_reported_as_missing(db: Session) -> None:
    owner = create_random_user(db)
    intruder = create_random_user(db)
    run_id = _recorded_run(db, owner, [_model_event()], AgentStatus.COMPLETED)

    with pytest.raises(service.RunNotFoundError):
        service.get_run(session=db, user_id=intruder.id, run_id=run_id)
    with pytest.raises(service.RunNotFoundError):
        service.list_run_events(session=db, user_id=intruder.id, run_id=run_id)

    rows, count = service.list_runs(session=db, user_id=intruder.id)
    assert count == 0
    assert rows == []
