"""项目库查不到要求时，现场读取院校官网。

只读官方域名，抽取结果直接回答用户，不写入证据库。
"""

from app.research.extractor import ExtractedRequirement, extract_requirements
from app.research.fetcher import FetchedPage, FetchError, fetch_official_page
from app.research.sources import OfficialSource, sources_for_program

__all__ = [
    "ExtractedRequirement",
    "FetchError",
    "FetchedPage",
    "OfficialSource",
    "extract_requirements",
    "fetch_official_page",
    "sources_for_program",
]
