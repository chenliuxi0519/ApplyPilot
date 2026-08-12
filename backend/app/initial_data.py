import logging

from sqlmodel import Session

from app.core.db import engine, init_db
from app.modules.programs.seed import seed_program_catalog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init() -> None:
    with Session(engine) as session:
        init_db(session)
        result = seed_program_catalog(session=session)
        logger.info(
            "Program catalog: universities created=%s updated=%s, "
            "programs created=%s updated=%s",
            result.universities_created,
            result.universities_updated,
            result.programs_created,
            result.programs_updated,
        )


def main() -> None:
    logger.info("正在创建初始数据")
    init()
    logger.info("初始数据创建完成")


if __name__ == "__main__":
    main()
