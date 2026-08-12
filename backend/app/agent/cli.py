import sys
import uuid
from typing import Any

from sqlmodel import Session

from app import crud
from app.agent.anthropic_client import AnthropicModelClient
from app.agent.loop import AgentLoop
from app.agent.state import AgentState, AgentStatus, PendingConfirmation
from app.core.config import settings
from app.core.db import engine
from app.harness import ExecutionContext
from app.models import User
from app.modules.agent_runs.recorder import PostgresRunRecorder
from app.modules.applications import service as application_service
from app.modules.programs import service as program_service
from app.tools import build_default_registry

EXIT_WORDS = {"exit", "quit", "退出"}
YES_WORDS = {"y", "yes", "是", "确认"}


def main() -> int:
    missing = settings.missing_agent_settings()
    if missing:
        print(
            f"尚未配置 {', '.join(missing)}。\n请在项目根目录的 .env 中补充配置后重试。"
        )
        return 1

    with Session(engine) as session:
        user = _demo_user(session)
        if user is None:
            print(
                f"没有找到初始管理员（{settings.FIRST_SUPERUSER}）。\n"
                "请先运行：python -m app.initial_data"
            )
            return 1

        loop = AgentLoop(
            model=AnthropicModelClient(),
            registry=build_default_registry(),
            session=session,
            execution=ExecutionContext(user_id=user.id, is_superuser=user.is_superuser),
            recorder=PostgresRunRecorder(engine),
        )

        print("ApplyPilot 智能助理")
        print(f"模型：{settings.AGENT_MODEL}   用户：{user.email}")
        print("输入“退出”、exit 或 quit 结束。\n")

        history: list[Any] = []
        while True:
            try:
                line = input("你：").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not line:
                continue
            if line.lower() in EXIT_WORDS:
                return 0

            state = AgentState.new(user_id=user.id, messages=history)
            state = loop.run(state, line)

            if state.status is AgentStatus.WAITING_CONFIRMATION:
                state = _resolve_confirmation(loop, session, user, state)

            _report(state)
            history = (
                list(state.messages) if state.status is AgentStatus.COMPLETED else []
            )


def _resolve_confirmation(
    loop: AgentLoop, session: Session, user: User, state: AgentState
) -> AgentState:
    pending = state.pending_confirmation
    assert pending is not None
    _print_confirmation(session, user, pending)
    try:
        answer = input("确认执行吗？[y/N]：").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer in YES_WORDS:
        return loop.resume_approved(state)
    return loop.resume_rejected(state)


def _print_confirmation(
    session: Session, user: User, pending: PendingConfirmation
) -> None:
    print("\n该操作需要确认，确认前不会执行任何修改。")
    application = _application_line(session, user, pending)
    if application is not None:
        program, current = application
        print(f"  项目：{program}")
        print(f"  当前状态：{current}")
    target = pending.arguments.get("target_status")
    if target is not None:
        print(f"  目标状态：{target}")
    print(f"  工具：{pending.tool_name}")
    print(f"  风险等级：{pending.permission_level.value}")
    print(f"  原因：{pending.reason}")
    if application is None:
        print(f"  参数：{_format(pending.arguments)}")
    print()


def _application_line(
    session: Session, user: User, pending: PendingConfirmation
) -> tuple[str, str] | None:
    raw_id = pending.arguments.get("application_id")
    if raw_id is None:
        return None
    try:
        application = application_service.get_application(
            session=session, user_id=user.id, application_id=uuid.UUID(str(raw_id))
        )
        program, university = program_service.get_program_with_university(
            session=session, program_id=application.program_id
        )
    except (ValueError, LookupError):
        return None

    label = (
        f"{university.short_name} - {program.name} ({application.application_cycle})"
    )
    return label, application.status.value


def _demo_user(session: Session) -> User | None:
    return crud.get_user_by_email(session=session, email=settings.FIRST_SUPERUSER)


def _report(state: AgentState) -> None:
    tools = [event.tool_name for event in state.trace if event.tool_name]
    if tools:
        print(f"\n[工具：{', '.join(tools)}]")
    print(f"[运行：{state.run_id}]")
    if state.observability_failures:
        print(
            f"[警告：{state.observability_failures} 条运行记录未保存："
            f"{state.last_observability_error}]"
        )

    if state.status is AgentStatus.COMPLETED:
        print(f"\n智能助理：\n{state.final_answer}\n")
        return

    if state.status is AgentStatus.WAITING_CONFIRMATION:
        print("\n智能助理：仍在等待确认，尚未执行任何操作。\n")
        return

    if state.status is AgentStatus.BUDGET_EXCEEDED:
        print(
            f"\n智能助理：达到运行上限，已执行 {state.step_count} 个步骤、"
            f"{state.tool_call_count} 次工具调用。\n"
        )
        return

    print(f"\n智能助理：运行失败（{state.status.value}）。")
    if state.last_error is not None:
        print(f"  {state.last_error.code.value}: {state.last_error.message}")
    print()


def _format(arguments: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value!r}" for key, value in arguments.items())


if __name__ == "__main__":
    sys.exit(main())
