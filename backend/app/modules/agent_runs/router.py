import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.agent.checkpointer import checkpoint_thread_id, get_checkpointer
from app.agent.state import AgentStatus
from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.models import Message
from app.modules.agent_runs import service
from app.modules.agent_runs.schemas import (
    AgentRunDetailPublic,
    AgentRunEventPublic,
    AgentRunEventsPublic,
    AgentRunPublic,
    AgentRunsPublic,
    RunMetricsPublic,
)

router = APIRouter(
    prefix="/agent/runs",
    tags=["agent-runs"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/", response_model=AgentRunsPublic)
def list_runs(
    session: SessionDep,
    current_user: CurrentUser,
    status: AgentStatus | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    rows, count = service.list_runs(
        session=session,
        user_id=current_user.id,
        status=status,
        skip=skip,
        limit=limit,
    )
    return AgentRunsPublic(
        data=[AgentRunPublic.model_validate(row) for row in rows], count=count
    )


@router.get("/{run_id}", response_model=AgentRunDetailPublic)
def read_run(session: SessionDep, current_user: CurrentUser, run_id: uuid.UUID) -> Any:
    try:
        replay = service.build_replay(
            session=session, user_id=current_user.id, run_id=run_id
        )
    except service.RunNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return AgentRunDetailPublic(
        **AgentRunPublic.model_validate(replay.run).model_dump(),
        metrics=RunMetricsPublic(**vars(replay.metrics)),
    )


@router.delete("/conversations/{conversation_id}", response_model=Message)
def delete_conversation(
    session: SessionDep, current_user: CurrentUser, conversation_id: str
) -> Any:
    if not service.conversation_exists(
        session=session, user_id=current_user.id, conversation_id=conversation_id
    ):
        raise HTTPException(status_code=404, detail="会话不存在")

    # Checkpoint 保存完整消息和工具结果，必须与展示用运行记录一并删除。
    # 先删 checkpoint：失败时运行记录仍可见，用户可以安全重试。
    get_checkpointer().delete_thread(
        checkpoint_thread_id(current_user.id, conversation_id)
    )
    try:
        service.delete_conversation(
            session=session, user_id=current_user.id, conversation_id=conversation_id
        )
    except service.RunNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Message(message="会话已删除")


@router.get("/{run_id}/events", response_model=AgentRunEventsPublic)
def read_run_events(
    session: SessionDep, current_user: CurrentUser, run_id: uuid.UUID
) -> Any:
    try:
        events = service.list_run_events(
            session=session, user_id=current_user.id, run_id=run_id
        )
    except service.RunNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return AgentRunEventsPublic(
        data=[AgentRunEventPublic.model_validate(event) for event in events],
        count=len(events),
    )
