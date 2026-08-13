from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from app.models import User
from app.modules.agent_runs.models import AgentRun, AgentRunEvent
from app.modules.applications.models import Application, ApplicationTask
from app.modules.profiles.models import ProfileFieldHistory, UserProfile
from app.modules.programs.models import (
    Program,
    ProgramRequirement,
    RequirementEvidence,
    RequirementReviewLog,
    University,
)
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session]:
    # 这个 fixture 结束时会清空所有业务表。库名里没有 test 就直接拒绝运行，
    # 免得对着开发库跑一次测试就把数据删干净。
    if "test" not in settings.POSTGRES_DB.lower():
        pytest.exit(
            f"拒绝在数据库 {settings.POSTGRES_DB!r} 上运行测试："
            "测试结束会清空所有业务表。请把 POSTGRES_DB 指向名字包含 test 的库，"
            "例如 POSTGRES_DB=applypilot_test。",
            returncode=1,
        )
    with Session(engine) as session:
        init_db(session)
        yield session
        session.exec(delete(AgentRunEvent))
        session.exec(delete(AgentRun))

        session.exec(delete(ApplicationTask))
        session.exec(delete(Application))

        session.exec(delete(RequirementReviewLog))
        session.exec(delete(ProgramRequirement))
        session.exec(delete(RequirementEvidence))
        session.exec(delete(Program))
        session.exec(delete(University))
        session.exec(delete(ProfileFieldHistory))
        session.exec(delete(UserProfile))
        statement = delete(User)
        session.exec(statement)
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
