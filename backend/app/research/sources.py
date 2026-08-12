"""项目到官方页面的映射，只登记验证过能稳定读取的 URL。

没登记的项目，Agent 会直接说读不到，不会去猜网址。
"""

from dataclasses import dataclass

from app.modules.programs.models import EvidenceSourceType


@dataclass(frozen=True)
class OfficialSource:
    url: str
    source_type: EvidenceSourceType
    # 校级页面（语言要求、招生日程）会被同校多个项目共用。
    university_level: bool = False


_NTU_ADMISSION_GUIDE = OfficialSource(
    "https://www.ntu.edu.sg/admissions/graduate/cwadmissionguide",
    EvidenceSourceType.ADMISSION_PAGE,
    university_level=True,
)

# 键为 (University.short_name, Program.name)，必须与项目库中的名称逐字一致。
OFFICIAL_SOURCES: dict[tuple[str, str], tuple[OfficialSource, ...]] = {
    ("NUS", "Master of Computing in Artificial Intelligence"): (
        OfficialSource(
            "https://www.comp.nus.edu.sg/programmes/pg/mcomp-ai/admissions/",
            EvidenceSourceType.ADMISSION_PAGE,
        ),
        OfficialSource(
            "https://www.comp.nus.edu.sg/programmes/pg/mcomp-ai/application/",
            EvidenceSourceType.PROGRAM_PAGE,
        ),
    ),
    ("NTU", "Master of Computing in Applied Artificial Intelligence"): (
        OfficialSource(
            "https://www.ntu.edu.sg/education/graduate-programme/"
            "master-of-computing-in-applied-ai-mcaai",
            EvidenceSourceType.PROGRAM_PAGE,
        ),
        _NTU_ADMISSION_GUIDE,
    ),
    ("NTU", "MSc Enterprise Artificial Intelligence"): (
        OfficialSource(
            "https://www.ntu.edu.sg/education/graduate-programme/"
            "master-of-science-in-enterprise-artificial-intelligence",
            EvidenceSourceType.PROGRAM_PAGE,
        ),
        _NTU_ADMISSION_GUIDE,
    ),
    ("NTU", "MSc Artificial Intelligence"): (
        OfficialSource(
            "https://www.ntu.edu.sg/computing/admissions/graduate-programmes/"
            "detail/master-of-science-in-artificial-intelligence",
            EvidenceSourceType.PROGRAM_PAGE,
        ),
        _NTU_ADMISSION_GUIDE,
    ),
    ("HKUST", "MSc Artificial Intelligence"): (
        OfficialSource(
            "https://prog-crs.hkust.edu.hk/pgprog/2026-27/msc-ai",
            EvidenceSourceType.PROGRAM_PAGE,
        ),
    ),
    ("HKUST", "MSc Information Technology"): (
        OfficialSource(
            "https://prog-crs.hkust.edu.hk/pgprog/2026-27/msc-it",
            EvidenceSourceType.PROGRAM_PAGE,
        ),
    ),
    ("HKUST", "MSc Big Data Technology"): (
        OfficialSource(
            "https://prog-crs.hkust.edu.hk/pgprog/2026-27/msc-bdt",
            EvidenceSourceType.PROGRAM_PAGE,
        ),
    ),
    # CUHK 的 MSc CS 有独立站点，按 WordPress 的 page_id 分页组织。
    ("CUHK", "MSc Computer Science"): (
        OfficialSource(
            "https://msc.cse.cuhk.edu.hk/?page_id=136&lang=en",
            EvidenceSourceType.ADMISSION_PAGE,
        ),
        OfficialSource(
            "https://msc.cse.cuhk.edu.hk/?page_id=142&lang=en",
            EvidenceSourceType.ADMISSION_PAGE,
        ),
        OfficialSource(
            "https://msc.cse.cuhk.edu.hk/?page_id=124&lang=en",
            EvidenceSourceType.FEES_PAGE,
        ),
    ),
    ("HKU", "MSc Computer Science"): (
        OfficialSource(
            "https://master.cds.hku.hk/msccs/admission/application-details/",
            EvidenceSourceType.ADMISSION_PAGE,
        ),
    ),
    ("Edinburgh", "MSc Artificial Intelligence"): (
        OfficialSource(
            "https://study.ed.ac.uk/postgraduate/degrees/index.php?r=site/view&id=107",
            EvidenceSourceType.PROGRAM_PAGE,
        ),
    ),
    ("Imperial", "MSc Computing (Artificial Intelligence and Machine Learning)"): (
        OfficialSource(
            "https://www.imperial.ac.uk/study/courses/postgraduate-taught/2026/"
            "computing-artificial-intelligence-msc/",
            EvidenceSourceType.PROGRAM_PAGE,
        ),
        OfficialSource(
            "https://www.imperial.ac.uk/study/apply/english-language/",
            EvidenceSourceType.UNIVERSITY_ENGLISH_REQUIREMENT,
            university_level=True,
        ),
    ),
}

# 抓不到的项目记下原因，重新加入目录时可以直接告诉用户。
UNAVAILABLE_REASONS: dict[tuple[str, str], str] = {
    ("UCL", "MSc Machine Learning"): "UCL 官网拒绝程序访问（HTTP 403）",
    (
        "UCL",
        "MSc Data Science and Machine Learning",
    ): "UCL 官网拒绝程序访问（HTTP 403）",
    ("UCL", "MSc Computer Science"): "UCL 官网拒绝程序访问（HTTP 403）",
}


def sources_for_program(
    *, university_short_name: str, program_name: str
) -> tuple[OfficialSource, ...]:
    return OFFICIAL_SOURCES.get((university_short_name, program_name), ())


def unavailable_reason(*, university_short_name: str, program_name: str) -> str | None:
    return UNAVAILABLE_REASONS.get((university_short_name, program_name))
