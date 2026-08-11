import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Session

from app.evaluation.case import FixtureData
from app.evaluation.gold_seed import ingest_gold_requirements
from app.modules.applications import service as application_service
from app.modules.applications.models import ApplicationStatus, TaskStatus, TaskType
from app.modules.applications.schemas import (
    ApplicationCreate,
    ApplicationUpdate,
    TaskUpdate,
)
from app.modules.profiles import service as profile_service
from app.modules.profiles.models import ProfileFieldSource, ProfileVerificationStatus
from app.modules.profiles.schemas import UserProfileUpdate
from app.modules.programs import service as program_service
from app.modules.programs.models import (
    DegreeType,
    EvidenceSourceType,
    Program,
    Region,
    RequirementFieldName,
    University,
)
from app.modules.programs.schemas import EvidenceCreate
from app.modules.programs.seed import seed_program_catalog

CYCLE = "2026/27"


SYNTHETIC_SOURCE_A = "https://conflict-source-a.invalid/requirements"
SYNTHETIC_SOURCE_B = "https://conflict-source-b.invalid/requirements"

FixtureBuilder = Callable[[Session, uuid.UUID], FixtureData]

_REGISTRY: dict[str, FixtureBuilder] = {}


class UnknownFixtureError(KeyError):
    pass


def fixture(name: str) -> Callable[[FixtureBuilder], FixtureBuilder]:
    def register(builder: FixtureBuilder) -> FixtureBuilder:
        if name in _REGISTRY:
            raise ValueError(f"Fixture {name} is already registered")
        _REGISTRY[name] = builder
        return builder

    return register


def build_fixture(name: str, *, session: Session, user_id: uuid.UUID) -> FixtureData:
    if name not in _REGISTRY:
        raise UnknownFixtureError(f"No fixture named {name}")
    return _REGISTRY[name](session, user_id)


def fixture_names() -> frozenset[str]:
    return frozenset(_REGISTRY)


def _profile_values() -> UserProfileUpdate:
    return UserProfileUpdate(
        undergraduate_university="Zhejiang University",
        undergraduate_major="Computer Science",
        gpa_value=Decimal("3.600"),
        gpa_scale=Decimal("4.000"),
        ielts_overall=Decimal("6.500"),
        target_regions=["singapore", "hong_kong"],
        target_fields=["ai"],
        career_goal="Machine learning engineer",
    )


def _create_profile(session: Session, user_id: uuid.UUID) -> None:
    profile_service.update_profile(
        session=session,
        user_id=user_id,
        profile_update=_profile_values(),
        source=ProfileFieldSource.USER_EXPLICIT,
        verification_status=ProfileVerificationStatus.USER_CONFIRMED,
        confidence=Decimal("1.000"),
    )


def _create_program(
    session: Session,
    *,
    name: str,
    university_short_name: str,
    region: Region = Region.SINGAPORE,
    field_tags: list[str] | None = None,
) -> Program:
    university = University(
        name=f"{university_short_name} University",
        short_name=university_short_name,
        region=region,
    )
    session.add(university)
    session.commit()
    session.refresh(university)

    program = Program(
        university_id=university.id,
        name=name,
        degree_type=DegreeType.TAUGHT_MASTER,
        field_tags=field_tags or ["ai"],
    )
    session.add(program)
    session.commit()
    session.refresh(program)
    return program


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _application(
    session: Session,
    user_id: uuid.UUID,
    program_id: uuid.UUID,
    *,
    status: ApplicationStatus | None = None,
    complete_required: bool = False,
) -> tuple[uuid.UUID, int]:
    application, _ = application_service.create_application(
        session=session,
        user_id=user_id,
        application_in=ApplicationCreate(
            program_id=program_id, application_cycle=CYCLE
        ),
    )
    if complete_required:
        for task in application_service.list_tasks(
            session=session, application_id=application.id
        ):
            if task.is_required and task.status is not TaskStatus.DONE:
                application_service.update_task(
                    session=session,
                    user_id=user_id,
                    task_id=task.id,
                    task_in=TaskUpdate(version=task.version, status=TaskStatus.DONE),
                )
        session.refresh(application)

    for target in _path_to(status):
        application = application_service.update_application(
            session=session,
            user_id=user_id,
            application_id=application.id,
            application_in=ApplicationUpdate(
                version=application.version, status=target, confirm=True
            ),
        )
    return application.id, application.version


def _path_to(status: ApplicationStatus | None) -> tuple[ApplicationStatus, ...]:
    if status is None or status is ApplicationStatus.SHORTLISTED:
        return ()
    if status is ApplicationStatus.PREPARING:
        return (ApplicationStatus.PREPARING,)
    if status is ApplicationStatus.READY_TO_SUBMIT:
        return (ApplicationStatus.PREPARING, ApplicationStatus.READY_TO_SUBMIT)
    if status is ApplicationStatus.SUBMITTED:
        return (
            ApplicationStatus.PREPARING,
            ApplicationStatus.READY_TO_SUBMIT,
            ApplicationStatus.SUBMITTED,
        )
    raise ValueError(f"No fixture path to {status}")


def _task_of(
    session: Session, application_id: uuid.UUID, task_type: TaskType
) -> tuple[uuid.UUID, int]:
    for task in application_service.list_tasks(
        session=session, application_id=application_id
    ):
        if task.task_type is task_type:
            return task.id, task.version
    raise LookupError(f"No {task_type.value} task on this application")


@fixture("empty")
def _empty(session: Session, user_id: uuid.UUID) -> FixtureData:
    del session
    return FixtureData(user_id=user_id)


@fixture("profile")
def _profile(session: Session, user_id: uuid.UUID) -> FixtureData:
    _create_profile(session, user_id)
    return FixtureData(user_id=user_id)


@fixture("catalog")
def _catalog(session: Session, user_id: uuid.UUID) -> FixtureData:
    seed_program_catalog(session=session)
    ingest_gold_requirements(session=session)
    return FixtureData(user_id=user_id)


@fixture("profile_and_catalog")
def _profile_and_catalog(session: Session, user_id: uuid.UUID) -> FixtureData:
    _create_profile(session, user_id)
    return _catalog(session, user_id)


@fixture("program")
def _program(session: Session, user_id: uuid.UUID) -> FixtureData:
    program = _create_program(
        session,
        name=_unique("MSc Machine Learning "),
        university_short_name=_unique("U"),
    )
    return FixtureData(user_id=user_id, values={"program_id": program.id})


@fixture("profile_and_program")
def _profile_and_program(session: Session, user_id: uuid.UUID) -> FixtureData:
    _create_profile(session, user_id)
    return _program(session, user_id)


@fixture("conflicted_requirement")
def _conflicted_requirement(session: Session, user_id: uuid.UUID) -> FixtureData:
    program = _create_program(
        session,
        name=_unique("MSc Artificial Intelligence "),
        university_short_name=_unique("U"),
    )
    captured = datetime(2026, 1, 15, tzinfo=UTC)
    for source_url, value in (
        (SYNTHETIC_SOURCE_A, "6.5"),
        (SYNTHETIC_SOURCE_B, "7.0"),
    ):
        program_service.ingest_evidence(
            session=session,
            program_id=program.id,
            evidence_in=EvidenceCreate(
                application_cycle=CYCLE,
                field_name=RequirementFieldName.IELTS_OVERALL,
                numeric_value=Decimal(value),
                source_url=source_url,
                source_type=EvidenceSourceType.PROGRAM_PAGE,
                captured_at=captured,
            ),
        )
    return FixtureData(user_id=user_id, values={"program_id": program.id})


@fixture("shortlisted_application")
def _shortlisted_application(session: Session, user_id: uuid.UUID) -> FixtureData:
    program = _create_program(
        session, name=_unique("MSc Computing "), university_short_name=_unique("U")
    )
    application_id, version = _application(session, user_id, program.id)
    return FixtureData(
        user_id=user_id,
        values={
            "program_id": program.id,
            "application_id": application_id,
            "application_version": version,
        },
    )


@fixture("preparing_application")
def _preparing_application(session: Session, user_id: uuid.UUID) -> FixtureData:
    program = _create_program(
        session, name=_unique("MSc Computing "), university_short_name=_unique("U")
    )
    application_id, version = _application(
        session, user_id, program.id, status=ApplicationStatus.PREPARING
    )
    cv_id, cv_version = _task_of(session, application_id, TaskType.CV)
    return FixtureData(
        user_id=user_id,
        values={
            "program_id": program.id,
            "application_id": application_id,
            "application_version": version,
            "cv_task_id": cv_id,
            "cv_task_version": cv_version,
        },
    )


@fixture("prepared_application")
def _prepared_application(session: Session, user_id: uuid.UUID) -> FixtureData:
    program = _create_program(
        session, name=_unique("MSc Computing "), university_short_name=_unique("U")
    )
    application_id, version = _application(
        session,
        user_id,
        program.id,
        status=ApplicationStatus.PREPARING,
        complete_required=True,
    )
    return FixtureData(
        user_id=user_id,
        values={
            "program_id": program.id,
            "application_id": application_id,
            "application_version": version,
        },
    )


@fixture("ready_application")
def _ready_application(session: Session, user_id: uuid.UUID) -> FixtureData:
    program = _create_program(
        session, name=_unique("MSc Computing "), university_short_name=_unique("U")
    )
    application_id, version = _application(
        session,
        user_id,
        program.id,
        status=ApplicationStatus.READY_TO_SUBMIT,
        complete_required=True,
    )
    return FixtureData(
        user_id=user_id,
        values={
            "program_id": program.id,
            "application_id": application_id,
            "application_version": version,
        },
    )


@fixture("submitted_application")
def _submitted_application(session: Session, user_id: uuid.UUID) -> FixtureData:
    program = _create_program(
        session, name=_unique("MSc Computing "), university_short_name=_unique("U")
    )
    application_id, version = _application(
        session,
        user_id,
        program.id,
        status=ApplicationStatus.SUBMITTED,
        complete_required=True,
    )
    return FixtureData(
        user_id=user_id,
        values={
            "program_id": program.id,
            "application_id": application_id,
            "application_version": version,
        },
    )


def registered() -> Mapping[str, FixtureBuilder]:
    return dict(_REGISTRY)
