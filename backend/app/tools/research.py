import uuid

from pydantic import BaseModel
from sqlmodel import Field, SQLModel

from app.harness import (
    PermissionLevel,
    ToolContext,
    ToolDefinition,
    ToolErrorCode,
    ToolExecutionError,
)
from app.modules.programs import service as program_service
from app.modules.programs.models import RequirementFieldName
from app.modules.programs.schemas import ApplicationCycle
from app.research import extract_requirements, fetch_official_page, sources_for_program
from app.research.fetcher import FetchError
from app.research.sources import unavailable_reason

MAX_PAGES_PER_CALL = 3


class ResearchProgramRequirementsInput(SQLModel):
    program_id: uuid.UUID
    application_cycle: ApplicationCycle | None = None


class ResearchedRequirement(SQLModel):
    field_name: RequirementFieldName
    value: str
    source_url: str
    source_quote: str


class ResearchProgramRequirementsOutput(SQLModel):
    program_id: uuid.UUID
    program: str
    university: str
    data: list[ResearchedRequirement] = Field(default_factory=list)
    count: int
    pages_read: list[str] = Field(default_factory=list)
    pages_failed: list[str] = Field(default_factory=list)
    verification_note: str


_VERIFICATION_NOTE = (
    "这些数值是刚刚从官方页面读取并自动抽取的，未经人工复核，也未写入项目库。"
    "向用户转述时必须说明来源网址与该情况；官网未写的字段不会出现在这里，"
    "不要替它们补充数值。"
)


def research_program_requirements(
    ctx: ToolContext, payload: ResearchProgramRequirementsInput
) -> BaseModel:
    try:
        program, university = program_service.get_program_with_university(
            session=ctx.session, program_id=payload.program_id
        )
    except program_service.ProgramNotFoundError as error:
        raise ToolExecutionError(ToolErrorCode.NOT_FOUND, str(error)) from error

    key = {
        "university_short_name": university.short_name,
        "program_name": program.name,
    }
    sources = sources_for_program(**key)
    if not sources:
        reason = unavailable_reason(**key) or "尚未登记该项目的官方页面地址"
        raise ToolExecutionError(
            ToolErrorCode.NOT_FOUND,
            f"无法读取 {university.short_name} {program.name} 的官方要求：{reason}。"
            "请向用户说明暂时无法提供该项目的官方数据，不要凭记忆作答。",
        )

    label = f"{university.name} {program.name}"
    collected: list[ResearchedRequirement] = []
    seen: set[tuple[RequirementFieldName, str]] = set()
    pages_read: list[str] = []
    pages_failed: list[str] = []

    for source in sources[:MAX_PAGES_PER_CALL]:
        try:
            page = fetch_official_page(source.url)
        except FetchError as error:
            pages_failed.append(f"{source.url}（{error}）")
            continue

        result = extract_requirements(
            page=page,
            program_label=label,
            application_cycle=payload.application_cycle,
        )
        pages_read.append(page.url)

        for requirement in result.requirements:
            # 同一字段在项目页与校级页都出现时，两条都保留，由 Agent 向用户点明差异。
            marker = (requirement.field_name, requirement.value_display)
            if marker in seen:
                continue
            seen.add(marker)
            collected.append(
                ResearchedRequirement(
                    field_name=requirement.field_name,
                    value=requirement.value_display,
                    source_url=requirement.source_url,
                    source_quote=requirement.source_quote,
                )
            )

    if not collected and not pages_read:
        raise ToolExecutionError(
            ToolErrorCode.NOT_FOUND,
            f"官方页面本次无法读取：{'；'.join(pages_failed)}。"
            "请向用户说明暂时读不到官网，不要凭记忆作答。",
        )

    return ResearchProgramRequirementsOutput(
        program_id=payload.program_id,
        program=program.name,
        university=university.name,
        data=collected,
        count=len(collected),
        pages_read=pages_read,
        pages_failed=pages_failed,
        verification_note=_VERIFICATION_NOTE,
    )


RESEARCH_PROGRAM_REQUIREMENTS = ToolDefinition(
    name="research_program_requirements",
    description=(
        "当 get_program_requirements 没有返回某个项目的已发布要求时，用这个工具"
        "现场读取该项目的官方页面并抽取申请要求。返回的数值来自官网实时抓取，"
        "未经人工复核，也不会写入项目库；转述给用户时必须说明来源网址和未复核状态。"
        "只有部分项目登记了官方页面地址，其余会返回未找到。"
    ),
    input_model=ResearchProgramRequirementsInput,
    output_model=ResearchProgramRequirementsOutput,
    permission_level=PermissionLevel.READ,
    handler=research_program_requirements,
)
