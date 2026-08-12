import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, func
from sqlmodel import Session, col, select

from app.agent.state import AgentStatus
from app.modules.agent_runs.metrics import RunMetrics, compute_metrics
from app.modules.agent_runs.models import AgentRun, AgentRunEvent
from app.modules.columns import get_datetime_utc


class RunNotFoundError(LookupError):
    pass


def save_run_presentation(
    *,
    session: Session,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    conversation_id: str,
    user_message: str | None,
    response_payload: dict[str, Any],
) -> None:
    run = get_run(session=session, user_id=user_id, run_id=run_id)
    run.conversation_id = conversation_id
    if user_message is not None:
        run.user_message = user_message
    run.response_payload = response_payload
    run.updated_at = get_datetime_utc()
    session.add(run)
    session.commit()


@dataclass
class RunReplay:
    run: AgentRun
    events: list[AgentRunEvent]
    metrics: RunMetrics


def list_runs(
    *,
    session: Session,
    user_id: uuid.UUID,
    status: AgentStatus | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[AgentRun], int]:
    conditions: list[ColumnElement[bool]] = [col(AgentRun.user_id) == user_id]
    if status is not None:
        conditions.append(col(AgentRun.status) == status)

    count_statement = select(func.count()).select_from(AgentRun)
    statement = select(AgentRun)
    for condition in conditions:
        count_statement = count_statement.where(condition)
        statement = statement.where(condition)

    count = session.exec(count_statement).one()
    rows = list(
        session.exec(
            statement.order_by(col(AgentRun.started_at).desc())
            .offset(skip)
            .limit(limit)
        ).all()
    )
    return rows, count


def get_run(*, session: Session, user_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun:
    statement = (
        select(AgentRun)
        .where(col(AgentRun.id) == run_id)
        .where(col(AgentRun.user_id) == user_id)
    )
    run = session.exec(statement).one_or_none()
    if run is None:
        raise RunNotFoundError("Agent 运行记录不存在")
    return run


def list_run_events(
    *, session: Session, user_id: uuid.UUID, run_id: uuid.UUID
) -> list[AgentRunEvent]:
    get_run(session=session, user_id=user_id, run_id=run_id)
    statement = (
        select(AgentRunEvent)
        .where(col(AgentRunEvent.run_id) == run_id)
        .order_by(col(AgentRunEvent.sequence))
    )
    return list(session.exec(statement).all())


def build_replay(
    *, session: Session, user_id: uuid.UUID, run_id: uuid.UUID
) -> RunReplay:
    run = get_run(session=session, user_id=user_id, run_id=run_id)
    events = list_run_events(session=session, user_id=user_id, run_id=run_id)
    return RunReplay(run=run, events=events, metrics=compute_metrics(run, events))


def format_replay(replay: RunReplay) -> list[str]:
    metrics = replay.metrics
    header = (
        f"Run {replay.run.id}  {replay.run.status.value}  "
        f"{metrics.total_steps} steps, {metrics.total_tool_calls} tool calls, "
        f"{metrics.confirmation_count} confirmations"
    )
    lines = [header]
    for event in replay.events:
        detail = " ".join(
            part
            for part in (
                event.tool_name,
                event.stop_reason,
                event.tool_result_status,
                event.final_status,
                event.error_code.value if event.error_code else None,
                f"{event.latency_ms}ms" if event.latency_ms else None,
            )
            if part
        )
        lines.append(
            f"  {event.sequence + 1:>2}  {event.event_type.value:<28} {detail}".rstrip()
        )
    return lines
