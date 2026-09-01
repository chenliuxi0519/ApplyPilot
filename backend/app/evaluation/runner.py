import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import Engine
from sqlmodel import Session

from app import crud
from app.agent.budget import Budget
from app.agent.graph import AgentRuntimeContext, build_graph, new_state
from app.agent.model import ModelClient
from app.agent.state import AgentState, AgentStatus
from app.context import build_business_context
from app.core.config import settings
from app.evaluation.case import EvaluationCase, FixtureData, ResumeDecision
from app.evaluation.effects import EffectResult, check_effect, fingerprint
from app.evaluation.fixtures import build_fixture
from app.evaluation.scoring import CaseOutcome, crashed, score_case
from app.evaluation.scripts import ScriptedModel, build_script
from app.models import User, UserCreate
from app.modules.agent_runs import service as run_service
from app.modules.agent_runs.recorder import PostgresRunRecorder
from app.tools import build_default_registry

EVAL_EMAIL_PREFIX = "applypilot-eval-"
EVAL_EMAIL_DOMAIN = "applypilot-evaluation.example.com"


class Mode(StrEnum):
    DETERMINISTIC = "deterministic"
    REAL = "real"


@dataclass(frozen=True)
class CaseRun:
    outcome: CaseOutcome
    run_id: uuid.UUID | None


def create_eval_user(session: Session) -> User:
    return crud.create_user(
        session=session,
        user_create=UserCreate(
            email=f"{EVAL_EMAIL_PREFIX}{uuid.uuid4().hex}@{EVAL_EMAIL_DOMAIN}",
            password=uuid.uuid4().hex,
        ),
    )


def delete_eval_user(session: Session, user_id: uuid.UUID) -> None:
    user = session.get(User, user_id)
    if user is None:
        return
    session.delete(user)
    session.commit()
    session.expunge_all()


def build_model(case: EvaluationCase, data: FixtureData, mode: Mode) -> ModelClient:
    if mode is Mode.DETERMINISTIC:
        if case.script is None:
            raise ValueError(
                f"{case.id} has no script and cannot run deterministically"
            )
        return ScriptedModel(build_script(case.script, data))

    from app.agent.anthropic_client import AgentNotConfiguredError, AnthropicModelClient

    missing = settings.missing_agent_settings()
    if missing:
        raise AgentNotConfiguredError(f"{', '.join(missing)} not set")
    return AnthropicModelClient()


def run_case(
    case: EvaluationCase,
    *,
    engine: Engine,
    mode: Mode = Mode.DETERMINISTIC,
    keep: bool = False,
) -> CaseRun:
    with Session(engine) as session:
        user = create_eval_user(session)
        user_id = user.id
        try:
            return _run(
                case, session=session, engine=engine, user_id=user_id, mode=mode
            )
        except Exception as error:  # noqa: BLE001 - one case must not stop the suite
            return CaseRun(
                outcome=crashed(case, f"{type(error).__name__}: {error}"), run_id=None
            )
        finally:
            if not keep:
                session.rollback()
                delete_eval_user(session, user_id)


def _run(
    case: EvaluationCase,
    *,
    session: Session,
    engine: Engine,
    user_id: uuid.UUID,
    mode: Mode,
) -> CaseRun:
    data = build_fixture(case.setup, session=session, user_id=user_id)
    before = fingerprint(session, user_id)

    model = build_model(case, data, mode)
    recorder = PostgresRunRecorder(engine, run_engine="graph")
    run_id = uuid.uuid4()
    recorder.start_run(AgentState(run_id=run_id, user_id=user_id))
    context = AgentRuntimeContext(
        user_id=user_id,
        is_superuser=False,
        model=model,
        registry=build_default_registry(),
        session=session,
        budget=case.budget or Budget(),
        recorder=recorder,
        business_context=lambda: build_business_context(
            session=session, user_id=user_id
        ),
    )
    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": f"eval:{user_id}:{run_id}"}}
    result = graph.invoke(
        new_state(run_id, case.render_message(data.values), model),
        config=config,
        context=context,
    )
    status = (
        AgentStatus.WAITING_CONFIRMATION
        if result.get("__interrupt__")
        else AgentStatus(result["status"])
    )

    effects: list[EffectResult] = []
    if status is AgentStatus.WAITING_CONFIRMATION and case.effect_at_pause:
        effects.append(
            check_effect(
                case.effect_at_pause, session=session, user_id=user_id, before=before
            )
        )

    if case.resume is not None and status is AgentStatus.WAITING_CONFIRMATION:
        result = graph.invoke(
            Command(resume={"approved": case.resume is ResumeDecision.APPROVE}),
            config=config,
            context=context,
        )
        status = AgentStatus(result["status"])

    effects.append(
        check_effect(
            case.expected_effect, session=session, user_id=user_id, before=before
        )
    )

    replay = run_service.build_replay(session=session, user_id=user_id, run_id=run_id)
    outcome = score_case(
        case,
        events=replay.events,
        metrics=replay.metrics,
        final_status=status,
        effects=effects,
    )
    return CaseRun(outcome=outcome, run_id=run_id)


def run_cases(
    cases: Sequence[EvaluationCase],
    *,
    engine: Engine,
    mode: Mode = Mode.DETERMINISTIC,
    keep: bool = False,
    repeat: int = 1,
    fail_fast: bool = False,
) -> list[CaseOutcome]:
    outcomes: list[CaseOutcome] = []
    for _ in range(max(repeat, 1)):
        for case in cases:
            result = run_case(case, engine=engine, mode=mode, keep=keep)
            outcomes.append(result.outcome)
            if fail_fast and not result.outcome.passed:
                return outcomes
    return outcomes
