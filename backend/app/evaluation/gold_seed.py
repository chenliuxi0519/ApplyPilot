import logging
from dataclasses import dataclass

from sqlmodel import Session, col, select

from app.evaluation.gold_programs import GOLD_REQUIREMENTS, GoldRequirement
from app.modules.programs import service as program_service
from app.modules.programs.models import Program, University

logger = logging.getLogger(__name__)


class GoldProgramMissingError(LookupError):
    pass


@dataclass
class GoldSeedResult:
    ingested: int
    programs: int
    outcomes: dict[str, int]


def _find_program(session: Session, requirement: GoldRequirement) -> Program:
    program = session.exec(
        select(Program)
        .join(University, onclause=col(Program.university_id) == col(University.id))
        .where(col(University.short_name) == requirement.university_short_name)
        .where(col(Program.name) == requirement.program_name)
    ).one_or_none()
    if program is None:
        raise GoldProgramMissingError(
            f"{requirement.university_short_name} "
            f"{requirement.program_name} is not in the catalog; "
            "请先运行 app.seed_programs"
        )
    return program


def ingest_gold_requirements(*, session: Session) -> GoldSeedResult:
    outcomes: dict[str, int] = {}
    programs: set[str] = set()
    for requirement in GOLD_REQUIREMENTS:
        program = _find_program(session, requirement)
        result = program_service.ingest_evidence(
            session=session,
            program_id=program.id,
            evidence_in=requirement.to_evidence(),
        )
        outcome = result.outcome.value
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        programs.add(f"{requirement.university_short_name}/{requirement.program_name}")
    return GoldSeedResult(
        ingested=len(GOLD_REQUIREMENTS),
        programs=len(programs),
        outcomes=outcomes,
    )
