from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlmodel import Session, col, select

from app.evaluation.gold_programs import (
    CAPTURED_AT,
    GOLD_REQUIREMENTS,
    OFFICIAL_DOMAIN_SUFFIXES,
    gold_programs,
)
from app.evaluation.gold_seed import ingest_gold_requirements
from app.modules.programs.models import (
    REQUIREMENT_FIELD_VALUE_TYPES,
    ProgramRequirement,
    RequirementEvidence,
    RequirementValueType,
)
from app.modules.programs.seed import PROGRAMS, UNIVERSITIES, seed_program_catalog
from app.research.sources import OFFICIAL_SOURCES

_SLOTS = {
    RequirementValueType.NUMERIC: ("numeric_value",),
    RequirementValueType.DATE: ("date_value",),
    RequirementValueType.MONEY: ("money_amount", "money_currency"),
    RequirementValueType.TEXT: ("text_value",),
    RequirementValueType.TEXT_LIST: ("text_list_value",),
}
_ALL_SLOTS = tuple(slot for slots in _SLOTS.values() for slot in slots)


def test_gold_data_covers_every_program_with_a_registered_official_source() -> None:
    """按需读取与 gold 数据来自同一批官方页面，两边应始终一致。"""
    assert set(gold_programs()) == set(OFFICIAL_SOURCES)


def test_every_source_is_the_university_itself() -> None:
    for requirement in GOLD_REQUIREMENTS:
        host = urlparse(requirement.source_url).hostname or ""
        assert any(
            host == suffix or host.endswith(f".{suffix}")
            for suffix in OFFICIAL_DOMAIN_SUFFIXES
        ), f"{requirement.source_url} is not an official university host"


def test_no_synthetic_source_leaked_into_the_gold_data() -> None:
    for requirement in GOLD_REQUIREMENTS:
        assert ".invalid" not in requirement.source_url


def test_every_entry_records_how_its_cycle_was_decided() -> None:
    for requirement in GOLD_REQUIREMENTS:
        assert requirement.basis.strip(), requirement.source_url
        assert requirement.application_cycle


def test_nothing_was_captured_in_the_future() -> None:
    assert CAPTURED_AT <= datetime.now(UTC)


def test_each_value_sits_in_the_slot_its_field_demands() -> None:
    for requirement in GOLD_REQUIREMENTS:
        expected = REQUIREMENT_FIELD_VALUE_TYPES[requirement.field_name]
        required = _SLOTS[expected]
        for slot in _ALL_SLOTS:
            value = getattr(requirement, slot)
            if slot in required:
                assert value is not None, f"{requirement.field_name} needs {slot}"
            else:
                assert value is None, f"{requirement.field_name} must not set {slot}"


def test_every_program_named_exists_in_the_catalog() -> None:
    known = {(program.university_short_name, program.name) for program in PROGRAMS}
    short_names = {university.short_name for university in UNIVERSITIES}
    for university_short_name, program_name in gold_programs():
        assert university_short_name in short_names
        assert (university_short_name, program_name) in known


def test_each_entry_converts_to_valid_evidence() -> None:
    for requirement in GOLD_REQUIREMENTS:
        evidence = requirement.to_evidence()
        assert evidence.application_cycle == requirement.application_cycle
        assert evidence.source_url == requirement.source_url


def test_ingesting_publishes_every_value_with_evidence_behind_it(db: Session) -> None:
    seed_program_catalog(session=db)
    result = ingest_gold_requirements(session=db)
    assert result.ingested == len(GOLD_REQUIREMENTS)

    db.expire_all()
    for requirement in GOLD_REQUIREMENTS:
        rows = db.exec(
            select(ProgramRequirement).where(
                col(ProgramRequirement.application_cycle)
                == requirement.application_cycle,
                col(ProgramRequirement.field_name) == requirement.field_name,
            )
        ).all()
        assert rows, f"{requirement.field_name} was not published"

    published = db.exec(select(ProgramRequirement)).all()
    assert published
    for row in published:
        assert row.published_evidence_id is not None
        assert db.get(RequirementEvidence, row.published_evidence_id) is not None


def test_ingesting_twice_changes_nothing(db: Session) -> None:
    seed_program_catalog(session=db)
    ingest_gold_requirements(session=db)
    second = ingest_gold_requirements(session=db)
    assert set(second.outcomes) == {"duplicate_ignored"}
