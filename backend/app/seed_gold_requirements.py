import logging

from sqlmodel import Session

from app.core.db import engine
from app.evaluation.gold_seed import ingest_gold_requirements

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("正在导入已核实的项目要求")
    with Session(engine) as session:
        result = ingest_gold_requirements(session=session)
    logger.info(
        "Ingested %s requirements across %s programs: %s",
        result.ingested,
        result.programs,
        result.outcomes,
    )


if __name__ == "__main__":
    main()
