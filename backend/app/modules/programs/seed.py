from dataclasses import dataclass

from sqlmodel import Session, col, select

from app.modules.columns import get_datetime_utc
from app.modules.programs.models import DegreeType, Program, Region, University


@dataclass(frozen=True)
class UniversitySeed:
    short_name: str
    name: str
    region: Region


@dataclass(frozen=True)
class ProgramSeed:
    university_short_name: str
    name: str
    field_tags: tuple[str, ...]
    degree_type: DegreeType = DegreeType.TAUGHT_MASTER


@dataclass
class SeedResult:
    universities_created: int
    universities_updated: int
    programs_created: int
    programs_updated: int


UNIVERSITIES: tuple[UniversitySeed, ...] = (
    UniversitySeed("NUS", "National University of Singapore", Region.SINGAPORE),
    UniversitySeed("NTU", "Nanyang Technological University", Region.SINGAPORE),
    UniversitySeed(
        "HKUST",
        "The Hong Kong University of Science and Technology",
        Region.HONG_KONG,
    ),
    UniversitySeed("CUHK", "The Chinese University of Hong Kong", Region.HONG_KONG),
    UniversitySeed("HKU", "The University of Hong Kong", Region.HONG_KONG),
    UniversitySeed("Imperial", "Imperial College London", Region.UNITED_KINGDOM),
    UniversitySeed("Edinburgh", "The University of Edinburgh", Region.UNITED_KINGDOM),
)

# 只收录官网课程列表里能查到、且能读到申请要求的项目。
PROGRAMS: tuple[ProgramSeed, ...] = (
    ProgramSeed("NUS", "Master of Computing in Artificial Intelligence", ("ai", "cs")),
    ProgramSeed("NTU", "MSc Artificial Intelligence", ("ai",)),
    ProgramSeed(
        "NTU",
        "Master of Computing in Applied Artificial Intelligence",
        ("ai", "cs"),
    ),
    ProgramSeed("NTU", "MSc Enterprise Artificial Intelligence", ("ai",)),
    ProgramSeed("HKUST", "MSc Artificial Intelligence", ("ai",)),
    ProgramSeed("HKUST", "MSc Information Technology", ("it", "cs")),
    ProgramSeed("HKUST", "MSc Big Data Technology", ("big_data", "data_science")),
    ProgramSeed("CUHK", "MSc Computer Science", ("cs",)),
    ProgramSeed("HKU", "MSc Computer Science", ("cs",)),
    ProgramSeed(
        "Imperial",
        "MSc Computing (Artificial Intelligence and Machine Learning)",
        ("ai", "ml", "cs"),
    ),
    ProgramSeed("Edinburgh", "MSc Artificial Intelligence", ("ai",)),
)


def seed_program_catalog(*, session: Session) -> SeedResult:
    result = SeedResult(0, 0, 0, 0)
    try:
        now = get_datetime_utc()
        universities: dict[str, University] = {}

        for seed in UNIVERSITIES:
            university = session.exec(
                select(University).where(col(University.short_name) == seed.short_name)
            ).one_or_none()
            if university is None:
                university = University(
                    short_name=seed.short_name, name=seed.name, region=seed.region
                )
                session.add(university)
                result.universities_created += 1
            elif university.name != seed.name or university.region != seed.region:
                university.name = seed.name
                university.region = seed.region
                university.updated_at = now
                session.add(university)
                result.universities_updated += 1
            universities[seed.short_name] = university

        session.flush()

        for program_seed in PROGRAMS:
            university = universities[program_seed.university_short_name]
            program = session.exec(
                select(Program)
                .where(col(Program.university_id) == university.id)
                .where(col(Program.name) == program_seed.name)
            ).one_or_none()
            tags = list(program_seed.field_tags)
            if program is None:
                session.add(
                    Program(
                        university_id=university.id,
                        name=program_seed.name,
                        degree_type=program_seed.degree_type,
                        field_tags=tags,
                    )
                )
                result.programs_created += 1
            elif (
                program.field_tags != tags
                or program.degree_type != program_seed.degree_type
            ):
                program.field_tags = tags
                program.degree_type = program_seed.degree_type
                program.updated_at = now
                session.add(program)
                result.programs_updated += 1

        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
