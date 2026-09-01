import os
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
from app.modules.preferences import UserPreference
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


def _destructive_run_allowed() -> bool:
    """测试结束会清空所有业务表，因此默认只允许对着一次性测试库跑。

    两种放行方式：库名里带 test，或显式设置 ALLOW_DESTRUCTIVE_TESTS=1
    （CI 用后者——那里的数据库是用完即弃的容器）。默认拒绝，
    免得对着开发库跑一次测试就把数据删干净。
    """
    if os.environ.get("ALLOW_DESTRUCTIVE_TESTS") == "1":
        return True
    return "test" in settings.POSTGRES_DB.lower()


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session]:
    if not _destructive_run_allowed():
        pytest.exit(
            f"拒绝在数据库 {settings.POSTGRES_DB!r} 上运行测试："
            "测试结束会清空所有业务表。请把 POSTGRES_DB 指向名字包含 test 的库"
            "（例如 applypilot_test），或在一次性环境中设置 "
            "ALLOW_DESTRUCTIVE_TESTS=1。",
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
        session.exec(delete(UserPreference))
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
