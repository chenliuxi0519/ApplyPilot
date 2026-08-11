"""按需读取院校官方页面，供 Agent 在项目库没有已发布要求时使用。

该模块只读取官方域名下的公开页面，抽取结果不写入证据库；它回答的是
"官网现在怎么写"，而不是"我们已核实的要求是什么"。
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
