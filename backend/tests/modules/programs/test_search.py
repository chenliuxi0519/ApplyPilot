from decimal import Decimal

from sqlmodel import Session

from app.modules.programs.models import DegreeType, Region
from app.modules.programs.schemas import ProgramSearchFilters
from app.modules.programs.service import ingest_evidence, search_programs
from tests.utils.program import (
    APPLICATION_CYCLE,
    create_random_program,
    create_random_university,
    tuition_evidence,
)


def test_search_filters_by_university_and_region(db: Session) -> None:
    university = create_random_university(db, region=Region.HONG_KONG)
    program = create_random_program(db, university=university)
    create_random_program(db)

    rows, count = search_programs(
        session=db,
        filters=ProgramSearchFilters(
            university=university.short_name, region=Region.HONG_KONG
        ),
    )

    assert count == 1
    assert [found.id for found, _ in rows] == [program.id]


def test_search_by_region_excludes_other_regions(db: Session) -> None:
    university = create_random_university(db, region=Region.SINGAPORE)
    create_random_program(db, university=university)

    _, count = search_programs(
        session=db,
        filters=ProgramSearchFilters(
            university=university.short_name, region=Region.UNITED_KINGDOM
        ),
    )

    assert count == 0


def test_search_matches_any_requested_field_tag(db: Session) -> None:
    university = create_random_university(db)
    machine_learning = create_random_program(
        db, university=university, field_tags=["ml", "data_science"]
    )
    create_random_program(db, university=university, field_tags=["it"])

    rows, count = search_programs(
        session=db,
        filters=ProgramSearchFilters(
            university=university.short_name, field_tags=["ml", "ai"]
        ),
    )

    assert count == 1
    assert [found.id for found, _ in rows] == [machine_learning.id]


def test_search_filters_by_degree_type(db: Session) -> None:
    university = create_random_university(db)
    create_random_program(db, university=university)

    _, count = search_programs(
        session=db,
        filters=ProgramSearchFilters(
            university=university.short_name, degree_type=DegreeType.PHD
        ),
    )

    assert count == 0


def test_search_matches_program_name_substring(db: Session) -> None:
    university = create_random_university(db)
    program = create_random_program(db, university=university)
    fragment = program.name.split()[-1][:10]

    rows, count = search_programs(
        session=db,
        filters=ProgramSearchFilters(university=university.short_name, query=fragment),
    )

    assert count == 1
    assert [found.id for found, _ in rows] == [program.id]


def test_budget_filter_compares_within_one_currency(db: Session) -> None:
    university = create_random_university(db)
    affordable = create_random_program(db, university=university)
    expensive = create_random_program(db, university=university)

    ingest_evidence(
        session=db,
        program_id=affordable.id,
        evidence_in=tuition_evidence(amount="50000", currency="SGD"),
    )
    ingest_evidence(
        session=db,
        program_id=expensive.id,
        evidence_in=tuition_evidence(amount="70000", currency="SGD"),
    )

    rows, count = search_programs(
        session=db,
        filters=ProgramSearchFilters(
            university=university.short_name,
            application_cycle=APPLICATION_CYCLE,
            max_tuition=Decimal("60000"),
            tuition_currency="SGD",
        ),
    )

    assert count == 1
    assert [found.id for found, _ in rows] == [affordable.id]


def test_budget_filter_ignores_tuition_in_another_currency(db: Session) -> None:
    university = create_random_university(db)
    program = create_random_program(db, university=university)
    ingest_evidence(
        session=db,
        program_id=program.id,
        evidence_in=tuition_evidence(amount="40000", currency="GBP"),
    )

    _, count = search_programs(
        session=db,
        filters=ProgramSearchFilters(
            university=university.short_name,
            application_cycle=APPLICATION_CYCLE,
            max_tuition=Decimal("1000000"),
            tuition_currency="SGD",
        ),
    )

    assert count == 0


def test_budget_filter_skips_programs_without_published_tuition(
    db: Session,
) -> None:
    university = create_random_university(db)
    create_random_program(db, university=university)

    _, count = search_programs(
        session=db,
        filters=ProgramSearchFilters(
            university=university.short_name,
            application_cycle=APPLICATION_CYCLE,
            max_tuition=Decimal("1000000"),
            tuition_currency="SGD",
        ),
    )

    assert count == 0


def test_budget_filter_is_scoped_to_the_requested_cycle(db: Session) -> None:
    university = create_random_university(db)
    program = create_random_program(db, university=university)
    ingest_evidence(
        session=db,
        program_id=program.id,
        evidence_in=tuition_evidence(
            amount="50000", currency="SGD", application_cycle="2025/26"
        ),
    )

    _, count = search_programs(
        session=db,
        filters=ProgramSearchFilters(
            university=university.short_name,
            application_cycle="2026/27",
            max_tuition=Decimal("1000000"),
            tuition_currency="SGD",
        ),
    )

    assert count == 0


def test_search_paginates_without_changing_the_total(db: Session) -> None:
    university = create_random_university(db)
    for _ in range(3):
        create_random_program(db, university=university)

    rows, count = search_programs(
        session=db,
        filters=ProgramSearchFilters(university=university.short_name, skip=1, limit=1),
    )

    assert count == 3
    assert len(rows) == 1
