import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel

from app.agent.anthropic_client import AgentNotConfiguredError, AnthropicModelClient
from app.agent.loop import AgentLoop, ResumeNotPendingError
from app.agent.model import ModelClient
from app.agent.session_store import (
    AgentSessionStore,
    PendingRunNotFoundError,
    session_store,
)
from app.agent.state import AgentState, AgentStatus, PendingConfirmation
from app.agent.ui_events import UiEventCollector, build_ui_registry, trace_label
from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.db import engine
from app.harness import ExecutionContext
from app.models import User
from app.modules.agent_runs import service as agent_run_service
from app.modules.agent_runs.recorder import PostgresRunRecorder
from app.modules.applications import service as application_service
from app.modules.profiles import service as profile_service
from app.modules.programs import service as program_service
from app.tools.registry import BUSINESS_TOOLS

router = APIRouter(prefix="/agent", tags=["agent"])


def get_model_client() -> ModelClient:
    try:
        return AnthropicModelClient()
    except AgentNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def get_session_store() -> AgentSessionStore:
    return session_store


ModelDep = Annotated[ModelClient, Depends(get_model_client)]
StoreDep = Annotated[AgentSessionStore, Depends(get_session_store)]


class AgentChatRequest(SQLModel):
    message: str
    conversation_id: str | None = None


class FieldChange(SQLModel):
    """一处待写入的字段改动，字段名保持原样，中文名由前端负责。"""

    field: str
    current: str | None = None
    next: str


class ConfirmationSummary(SQLModel):
    application_id: uuid.UUID | None = None
    program_label: str | None = None
    application_cycle: str | None = None
    current_status: str | None = None
    target_status: str | None = None
    changes: list[FieldChange] = []


class ConfirmationPublic(SQLModel):
    call_id: str
    tool_name: str
    permission_level: str
    reason: str
    summary: ConfirmationSummary


class ToolTracePublic(SQLModel):
    label: str
    status: str


class UiEventPublic(SQLModel):
    type: str
    data: dict[str, Any]


class AgentChatPublic(SQLModel):
    run_id: uuid.UUID
    conversation_id: str
    status: AgentStatus
    answer: str | None = None
    confirmation: ConfirmationPublic | None = None
    tool_trace: list[ToolTracePublic] = []
    ui_events: list[UiEventPublic] = []
    steps: int = 0
    tool_calls: int = 0
    error: str | None = None


def _build_loop(
    session: Session, user: User, model: ModelClient, collector: UiEventCollector
) -> AgentLoop:
    return AgentLoop(
        model=model,
        registry=build_ui_registry(collector, BUSINESS_TOOLS),
        session=session,
        execution=ExecutionContext(user_id=user.id, is_superuser=user.is_superuser),
        recorder=PostgresRunRecorder(engine),
    )


def _display(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, list):
        return "、".join(str(item) for item in value) if value else "—"
    return str(value)


def _profile_changes(
    session: Session, user: User, arguments: dict[str, Any]
) -> list[FieldChange]:
    """列出档案更新会改动的字段，附上当前值，便于用户逐项核对。"""
    try:
        profile = profile_service.get_profile_or_raise(session=session, user_id=user.id)
    except profile_service.ProfileNotFoundError:
        profile = None

    changes: list[FieldChange] = []
    for field, value in arguments.items():
        current = None if profile is None else getattr(profile, field, None)
        changes.append(
            FieldChange(
                field=field,
                current=None if profile is None else _display(current),
                next=_display(value),
            )
        )
    return changes


def _summary(
    session: Session, user: User, pending: PendingConfirmation
) -> ConfirmationSummary:
    raw_id = pending.arguments.get("application_id")
    target = pending.arguments.get("target_status")
    summary = ConfirmationSummary(target_status=None if target is None else str(target))

    if pending.tool_name == "update_user_profile":
        summary.changes = _profile_changes(session, user, pending.arguments)
        return summary

    if raw_id is None:
        return summary
    try:
        application = application_service.get_application(
            session=session, user_id=user.id, application_id=uuid.UUID(str(raw_id))
        )
        program, university = program_service.get_program_with_university(
            session=session, program_id=application.program_id
        )
    except (ValueError, LookupError):
        return summary

    summary.application_id = application.id
    summary.program_label = f"{university.short_name} {program.name}"
    summary.application_cycle = application.application_cycle
    summary.current_status = application.status.value
    return summary


def _respond(
    state: AgentState,
    *,
    session: Session,
    user: User,
    conversation_id: str,
    collector: UiEventCollector,
    store: AgentSessionStore,
    user_message: str | None = None,
) -> AgentChatPublic:
    confirmation: ConfirmationPublic | None = None
    if state.status is AgentStatus.WAITING_CONFIRMATION:
        pending = state.pending_confirmation
        assert pending is not None

        store.remember_pending(state, conversation_id=conversation_id)
        confirmation = ConfirmationPublic(
            call_id=pending.call_id,
            tool_name=pending.tool_name,
            permission_level=pending.permission_level.value,
            reason=pending.reason,
            summary=_summary(session, user, pending),
        )
    elif state.status is AgentStatus.COMPLETED:
        store.remember_conversation(
            conversation_id, messages=state.messages, user_id=user.id
        )
    else:
        store.forget_conversation(conversation_id)

    response = AgentChatPublic(
        run_id=state.run_id,
        conversation_id=conversation_id,
        status=state.status,
        answer=state.final_answer,
        confirmation=confirmation,
        tool_trace=[
            ToolTracePublic(
                label=trace_label(event.tool_name),
                status=event.tool_result_status or "ok",
            )
            for event in state.trace
            if event.tool_name is not None and event.tool_result_status is not None
        ],
        ui_events=[UiEventPublic(**event) for event in collector.as_dicts()],
        steps=state.step_count,
        tool_calls=state.tool_call_count,
        error=None if state.last_error is None else state.last_error.code.value,
    )

    with Session(engine) as history_session:
        agent_run_service.save_run_presentation(
            session=history_session,
            user_id=user.id,
            run_id=state.run_id,
            conversation_id=conversation_id,
            user_message=user_message,
            response_payload=response.model_dump(mode="json"),
        )
    return response


@router.post("/chat", response_model=AgentChatPublic)
def chat(
    session: SessionDep,
    current_user: CurrentUser,
    store: StoreDep,
    model: ModelDep,
    body: AgentChatRequest,
) -> AgentChatPublic:
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="请输入消息内容")

    conversation_id = body.conversation_id or f"c-{uuid.uuid4().hex}"
    collector = UiEventCollector()
    loop = _build_loop(session, current_user, model, collector)

    state = AgentState.new(
        user_id=current_user.id,
        messages=store.conversation(conversation_id, user_id=current_user.id),
    )
    state = loop.run(state, message)
    return _respond(
        state,
        session=session,
        user=current_user,
        conversation_id=conversation_id,
        collector=collector,
        store=store,
        user_message=message,
    )


def _resume(
    *,
    run_id: uuid.UUID,
    approved: bool,
    session: Session,
    current_user: User,
    store: AgentSessionStore,
    model: ModelClient,
) -> AgentChatPublic:
    try:
        pending = store.take_pending(run_id, user_id=current_user.id)
    except PendingRunNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    state = pending.state

    collector = UiEventCollector()
    loop = _build_loop(session, current_user, model, collector)
    try:
        state = loop.resume_approved(state) if approved else loop.resume_rejected(state)
    except ResumeNotPendingError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return _respond(
        state,
        session=session,
        user=current_user,
        conversation_id=pending.conversation_id,
        collector=collector,
        store=store,
    )


@router.post("/runs/{run_id}/approve", response_model=AgentChatPublic)
def approve(
    run_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    store: StoreDep,
    model: ModelDep,
) -> AgentChatPublic:
    return _resume(
        run_id=run_id,
        approved=True,
        session=session,
        current_user=current_user,
        store=store,
        model=model,
    )


@router.post("/runs/{run_id}/reject", response_model=AgentChatPublic)
def reject(
    run_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    store: StoreDep,
    model: ModelDep,
) -> AgentChatPublic:
    return _resume(
        run_id=run_id,
        approved=False,
        session=session,
        current_user=current_user,
        store=store,
        model=model,
    )


class AgentConfigPublic(SQLModel):
    configured: bool


@router.get("/config", response_model=AgentConfigPublic)
def agent_config(current_user: CurrentUser) -> AgentConfigPublic:
    del current_user
    return AgentConfigPublic(configured=settings.agent_is_configured)
