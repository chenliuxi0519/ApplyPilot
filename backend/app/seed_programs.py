import logging

from sqlmodel import Session

from app.core.db import engine
from app.modules.programs.seed import seed_program_catalog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("正在初始化项目目录")
    with Session(engine) as session:
        result = seed_program_catalog(session=session)
    logger.info(
        "Universities created=%s updated=%s, programs created=%s updated=%s",
        result.universities_created,
        result.universities_updated,
        result.programs_created,
        result.programs_updated,
    )


if __name__ == "__main__":
    main()
