from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from app.modules.programs.models import EvidenceSourceType, RequirementFieldName
from app.modules.programs.schemas import EvidenceCreate

CAPTURED_AT = datetime(2026, 8, 9, tzinfo=UTC)


OFFICIAL_DOMAIN_SUFFIXES = (
    "nus.edu.sg",
    "ntu.edu.sg",
    "hkust.edu.hk",
    "hku.hk",
    "cuhk.edu.hk",
    "imperial.ac.uk",
    "ucl.ac.uk",
    "ed.ac.uk",
)


@dataclass(frozen=True)
class GoldRequirement:
    university_short_name: str
    program_name: str
    application_cycle: str
    field_name: RequirementFieldName
    source_url: str
    source_type: EvidenceSourceType
    basis: str
    numeric_value: Decimal | None = None
    date_value: date | None = None
    money_amount: Decimal | None = None
    money_currency: str | None = None
    text_value: str | None = None
    text_list_value: tuple[str, ...] | None = None

    def to_evidence(self) -> EvidenceCreate:
        return EvidenceCreate(
            application_cycle=self.application_cycle,
            field_name=self.field_name,
            source_url=self.source_url,
            source_type=self.source_type,
            captured_at=CAPTURED_AT,
            numeric_value=self.numeric_value,
            date_value=self.date_value,
            money_amount=self.money_amount,
            money_currency=self.money_currency,
            text_value=self.text_value,
            text_list_value=None
            if self.text_list_value is None
            else list(self.text_list_value),
        )


_NUS_ADMISSIONS = "https://www.comp.nus.edu.sg/programmes/pg/mcomp-ai/admissions/"
_NUS_APPLICATION = "https://www.comp.nus.edu.sg/programmes/pg/mcomp-ai/application/"
_NUS_CYCLE_BASIS = (
    "The application page gives one intake, opening 1 October 2025 and closing "
    "31 January 2026. The August intake that follows that window is August "
    "2026, which is academic year 2026/27."
)

_NTU_PROGRAMME = (
    "https://www.ntu.edu.sg/education/graduate-programme/"
    "master-of-science-in-artificial-intelligence"
)
_NTU_CYCLE_BASIS = (
    "The programme page states its fee as applying to 'Academic Year 2025/26 "
    "and after'; 2025/26 is the only academic year the page names, so it is "
    "the cycle used for everything read from it."
)

_HKUST_CATALOG = "https://prog-crs.hkust.edu.hk/pgprog/2026-27/msc-ai"
_HKUST_CYCLE_BASIS = "The catalogue itself is the 2026-27 edition."

_HKU_APPLICATION = "https://master.cds.hku.hk/msccs/admission/application-details/"
_HKU_CYCLE_BASIS = "The page states '2026/27 Fall intake (September 2026)'."

_EDINBURGH_DEGREE = (
    "https://study.ed.ac.uk/postgraduate/degrees/index.php?r=site/view&id=107"
)
_EDINBURGH_CYCLE_BASIS = (
    "The page states 'Year of entry: 2026', which is the 2026/27 academic year."
)


GOLD_REQUIREMENTS: tuple[GoldRequirement, ...] = (
    GoldRequirement(
        university_short_name="NUS",
        program_name="Master of Computing in Artificial Intelligence",
        application_cycle="2026/27",
        field_name=RequirementFieldName.IELTS_OVERALL,
        numeric_value=Decimal("6.0"),
        source_url=_NUS_ADMISSIONS,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=_NUS_CYCLE_BASIS,
    ),
    GoldRequirement(
        university_short_name="NUS",
        program_name="Master of Computing in Artificial Intelligence",
        application_cycle="2026/27",
        field_name=RequirementFieldName.DEGREE_BACKGROUND,
        text_value=(
            "A good honours degree in computing; or a good honours degree in a "
            "related discipline with 2 years IT industry experience; or a good "
            "bachelor's degree in computing with 2 years IT industry "
            "experience; or a good bachelor's or honours degree in a business "
            "related discipline with 2 years IT industry experience"
        ),
        source_url=_NUS_ADMISSIONS,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=_NUS_CYCLE_BASIS,
    ),
    GoldRequirement(
        university_short_name="NUS",
        program_name="Master of Computing in Artificial Intelligence",
        application_cycle="2026/27",
        field_name=RequirementFieldName.APPLICATION_DEADLINE,
        date_value=date(2026, 1, 31),
        source_url=_NUS_APPLICATION,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=(
            f"{_NUS_CYCLE_BASIS} The page gives the closing date as 31 January 2026."
        ),
    ),
    GoldRequirement(
        university_short_name="NTU",
        program_name="MSc Artificial Intelligence",
        application_cycle="2025/26",
        field_name=RequirementFieldName.IELTS_OVERALL,
        numeric_value=Decimal("6.5"),
        source_url=_NTU_PROGRAMME,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=_NTU_CYCLE_BASIS,
    ),
    GoldRequirement(
        university_short_name="NTU",
        program_name="MSc Artificial Intelligence",
        application_cycle="2025/26",
        field_name=RequirementFieldName.TOEFL_OVERALL,
        numeric_value=Decimal("100"),
        source_url=_NTU_PROGRAMME,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=_NTU_CYCLE_BASIS,
    ),
    GoldRequirement(
        university_short_name="NTU",
        program_name="MSc Artificial Intelligence",
        application_cycle="2025/26",
        field_name=RequirementFieldName.DEGREE_BACKGROUND,
        text_value=(
            "A good honours degree in computer science, computer engineering "
            "or a related discipline with solid mathematical training; or a "
            "good bachelor's degree in computer science, computer engineering "
            "or a related discipline with solid mathematical training and "
            "2 years relevant industry experience"
        ),
        source_url=_NTU_PROGRAMME,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=_NTU_CYCLE_BASIS,
    ),
    GoldRequirement(
        university_short_name="NTU",
        program_name="MSc Artificial Intelligence",
        application_cycle="2025/26",
        field_name=RequirementFieldName.TUITION,
        money_amount=Decimal("63220"),
        money_currency="SGD",
        source_url=_NTU_PROGRAMME,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=(
            f"{_NTU_CYCLE_BASIS} The page states 'S$63,220' as the fee for "
            "Academic Year 2025/26 and after."
        ),
    ),
    GoldRequirement(
        university_short_name="HKUST",
        program_name="MSc Artificial Intelligence",
        application_cycle="2026/27",
        field_name=RequirementFieldName.IELTS_OVERALL,
        numeric_value=Decimal("6.5"),
        source_url=_HKUST_CATALOG,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=_HKUST_CYCLE_BASIS,
    ),
    GoldRequirement(
        university_short_name="HKUST",
        program_name="MSc Artificial Intelligence",
        application_cycle="2026/27",
        field_name=RequirementFieldName.IELTS_MIN_BAND,
        numeric_value=Decimal("5.5"),
        source_url=_HKUST_CATALOG,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=f"{_HKUST_CYCLE_BASIS} The page states 'All sub-score: 5.5'.",
    ),
    GoldRequirement(
        university_short_name="HKUST",
        program_name="MSc Artificial Intelligence",
        application_cycle="2026/27",
        field_name=RequirementFieldName.DEGREE_BACKGROUND,
        text_value=(
            "A bachelor's degree in Computer Engineering, Computer Science or "
            "a related discipline, or a bachelor's degree in other disciplines "
            "with at least two years of post-qualification work experience "
            "relevant to the program"
        ),
        source_url=_HKUST_CATALOG,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=_HKUST_CYCLE_BASIS,
    ),
    GoldRequirement(
        university_short_name="HKUST",
        program_name="MSc Artificial Intelligence",
        application_cycle="2026/27",
        field_name=RequirementFieldName.TUITION,
        money_amount=Decimal("400000"),
        money_currency="HKD",
        source_url=_HKUST_CATALOG,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=f"{_HKUST_CYCLE_BASIS} The page states 'HK$400,000'.",
    ),
    GoldRequirement(
        university_short_name="HKUST",
        program_name="MSc Artificial Intelligence",
        application_cycle="2026/27",
        field_name=RequirementFieldName.APPLICATION_DEADLINE,
        date_value=date(2026, 3, 1),
        source_url=_HKUST_CATALOG,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=(
            f"{_HKUST_CYCLE_BASIS} The page lists three rounds — 1 Nov 2025, "
            "1 Jan 2026, 1 Mar 2026 — and the final round is recorded as the "
            "deadline."
        ),
    ),
    GoldRequirement(
        university_short_name="HKU",
        program_name="MSc Computer Science",
        application_cycle="2026/27",
        field_name=RequirementFieldName.DEGREE_BACKGROUND,
        text_value=(
            "Shall hold a Bachelor's degree of this University or a "
            "qualification of equivalent standard"
        ),
        source_url=_HKU_APPLICATION,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=_HKU_CYCLE_BASIS,
    ),
    GoldRequirement(
        university_short_name="HKU",
        program_name="MSc Computer Science",
        application_cycle="2026/27",
        field_name=RequirementFieldName.APPLICATION_DEADLINE,
        date_value=date(2026, 4, 30),
        source_url=_HKU_APPLICATION,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=(
            f"{_HKU_CYCLE_BASIS} The page gives a main round of 1 Dec 2025 and "
            "a clearing round of 30 Apr 2026; the clearing round is recorded "
            "as the deadline."
        ),
    ),
    GoldRequirement(
        university_short_name="Edinburgh",
        program_name="MSc Artificial Intelligence",
        application_cycle="2026/27",
        field_name=RequirementFieldName.IELTS_OVERALL,
        numeric_value=Decimal("7.0"),
        source_url=_EDINBURGH_DEGREE,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=_EDINBURGH_CYCLE_BASIS,
    ),
    GoldRequirement(
        university_short_name="Edinburgh",
        program_name="MSc Artificial Intelligence",
        application_cycle="2026/27",
        field_name=RequirementFieldName.IELTS_MIN_BAND,
        numeric_value=Decimal("6.5"),
        source_url=_EDINBURGH_DEGREE,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=(
            f"{_EDINBURGH_CYCLE_BASIS} The page states 'total 7.0 with at "
            "least 6.5 in each component'."
        ),
    ),
    GoldRequirement(
        university_short_name="Edinburgh",
        program_name="MSc Artificial Intelligence",
        application_cycle="2026/27",
        field_name=RequirementFieldName.DEGREE_BACKGROUND,
        text_value=(
            "A UK 2:1 honours degree, or its international equivalent, in "
            "informatics, artificial intelligence, cognitive science, computer "
            "science, econometrics, electrical engineering, linguistics, "
            "mathematics, philosophy, physics or psychology"
        ),
        source_url=_EDINBURGH_DEGREE,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=_EDINBURGH_CYCLE_BASIS,
    ),
    GoldRequirement(
        university_short_name="Edinburgh",
        program_name="MSc Artificial Intelligence",
        application_cycle="2026/27",
        field_name=RequirementFieldName.APPLICATION_DEADLINE,
        date_value=date(2026, 3, 31),
        source_url=_EDINBURGH_DEGREE,
        source_type=EvidenceSourceType.PROGRAM_PAGE,
        basis=(
            f"{_EDINBURGH_CYCLE_BASIS} The page gives the application deadline "
            "as 31 March 2026."
        ),
    ),
)


def gold_programs() -> tuple[tuple[str, str], ...]:
    seen: list[tuple[str, str]] = []
    for requirement in GOLD_REQUIREMENTS:
        key = (requirement.university_short_name, requirement.program_name)
        if key not in seen:
            seen.append(key)
    return tuple(seen)
