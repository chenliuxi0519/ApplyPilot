import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlmodel import Field, SQLModel

from app.harness import (
    PermissionLevel,
    ToolContext,
    ToolDefinition,
    ToolErrorCode,
    ToolExecutionError,
)
from app.modules.profiles import service as profile_service
from app.modules.programs import service as program_service
from app.modules.programs.fit import FitBand, evaluate_fit, has_disputed
from app.modules.programs.models import (
    DegreeType,
    ProgramRequirement,
    Region,
    RequirementFieldName,
    RequirementStatus,
    RequirementValueType,
)
from app.modules.programs.schemas import ApplicationCycle, ProgramSearchFilters


class ProgramSummary(SQLModel):
    program_id: uuid.UUID
    name: str
    university: str
    region: Region
    degree_type: DegreeType
    field_tags: list[str]


class SearchProgramsOutput(SQLModel):
    data: list[ProgramSummary]
    count: int


class GetProgramRequirementsInput(SQLModel):
    program_id: uuid.UUID
    application_cycle: ApplicationCycle | None = None


class RequirementSummary(SQLModel):
    field_name: RequirementFieldName
    application_cycle: str
    value: str

    status: RequirementStatus

    source_url: str | None = None
    captured_at: str | None = None


class GetProgramRequirementsOutput(SQLModel):
    program_id: uuid.UUID
    data: list[RequirementSummary]
    count: int


def _format_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return format(normalized, "f")


def _format_value(requirement: ProgramRequirement) -> str:
    if requirement.value_type is RequirementValueType.NUMERIC:
        assert requirement.numeric_value is not None
        return _format_decimal(requirement.numeric_value)
    if requirement.value_type is RequirementValueType.DATE:
        assert requirement.date_value is not None
        return requirement.date_value.isoformat()
    if requirement.value_type is RequirementValueType.MONEY:
        assert requirement.money_amount is not None
        return (
            f"{_format_decimal(requirement.money_amount)} {requirement.money_currency}"
        )
    if requirement.value_type is RequirementValueType.TEXT:
        assert requirement.text_value is not None
        return requirement.text_value
    assert requirement.text_list_value is not None
    return ", ".join(requirement.text_list_value)


def search_programs(ctx: ToolContext, payload: ProgramSearchFilters) -> BaseModel:
    rows, count = program_service.search_programs(session=ctx.session, filters=payload)
    return SearchProgramsOutput(
        data=[
            ProgramSummary(
                program_id=program.id,
                name=program.name,
                university=university.short_name,
                region=university.region,
                degree_type=program.degree_type,
                field_tags=program.field_tags,
            )
            for program, university in rows
        ],
        count=count,
    )


def get_program_requirements(
    ctx: ToolContext, payload: GetProgramRequirementsInput
) -> BaseModel:
    try:
        program_service.get_program_or_raise(
            session=ctx.session, program_id=payload.program_id
        )
    except program_service.ProgramNotFoundError as error:
        raise ToolExecutionError(ToolErrorCode.NOT_FOUND, str(error)) from error

    requirements = program_service.list_requirements(
        session=ctx.session,
        program_id=payload.program_id,
        application_cycle=payload.application_cycle,
    )

    evidence_by_id = program_service.list_evidence_by_id(
        session=ctx.session,
        evidence_ids=[
            r.published_evidence_id for r in requirements if r.published_evidence_id
        ],
    )
    return GetProgramRequirementsOutput(
        program_id=payload.program_id,
        data=[
            RequirementSummary(
                field_name=requirement.field_name,
                application_cycle=requirement.application_cycle,
                value=_format_value(requirement),
                status=requirement.status,
                source_url=(
                    evidence_by_id[requirement.published_evidence_id].source_url
                    if requirement.published_evidence_id in evidence_by_id
                    else None
                ),
                captured_at=(
                    evidence_by_id[
                        requirement.published_evidence_id
                    ].captured_at.isoformat()
                    if requirement.published_evidence_id in evidence_by_id
                    else None
                ),
            )
            for requirement in requirements
        ],
        count=len(requirements),
    )


SEARCH_PROGRAMS = ToolDefinition(
    name="search_programs",
    description=(
        "Search the curated program catalog by region, university, degree "
        "type, subject tags, free text, or a tuition budget. A tuition budget "
        "is compared inside one currency and needs both tuition_currency and "
        "application_cycle."
    ),
    input_model=ProgramSearchFilters,
    output_model=SearchProgramsOutput,
    permission_level=PermissionLevel.READ,
    handler=search_programs,
)


class FitFactorSummary(SQLModel):
    field: str
    required: str
    have: str
    delta: str


class ProgramFitPublic(SQLModel):
    program_id: uuid.UUID
    name: str
    university: str
    application_cycle: str | None
    band: FitBand
    gaps: list[FitFactorSummary]
    strengths: list[FitFactorSummary]
    context: list[dict[str, str]]
    disputed: bool


class CompareProgramsInput(SQLModel):
    program_ids: list[uuid.UUID] = Field(min_length=1, max_length=8)
    application_cycle: ApplicationCycle | None = None


class CompareProgramsOutput(SQLModel):
    data: list[ProgramFitPublic]
    profile_missing: list[str]
    count: int


def _summarize(factors: list[Any]) -> list[FitFactorSummary]:
    return [
        FitFactorSummary(
            field=factor.field,
            required=factor.required,
            have=factor.have,
            delta=factor.delta,
        )
        for factor in factors
    ]


def compare_programs(ctx: ToolContext, payload: CompareProgramsInput) -> BaseModel:
    try:
        profile = profile_service.get_profile_or_raise(
            session=ctx.session, user_id=ctx.user_id
        )
    except profile_service.ProfileNotFoundError:
        profile = None

    seen_missing: list[str] = []
    fits: list[ProgramFitPublic] = []
    for program_id in payload.program_ids:
        try:
            program, university = program_service.get_program_with_university(
                session=ctx.session, program_id=program_id
            )
        except program_service.ProgramNotFoundError as error:
            raise ToolExecutionError(ToolErrorCode.NOT_FOUND, str(error)) from error

        requirements = program_service.list_requirements(
            session=ctx.session,
            program_id=program_id,
            application_cycle=payload.application_cycle,
        )
        result = evaluate_fit(profile, requirements)
        for name in result.profile_missing:
            if name not in seen_missing:
                seen_missing.append(name)
        fits.append(
            ProgramFitPublic(
                program_id=program.id,
                name=program.name,
                university=university.short_name,
                application_cycle=payload.application_cycle,
                band=result.band,
                gaps=_summarize(list(result.gaps)),
                strengths=_summarize(list(result.strengths)),
                context=[
                    {"field": field_name, "value": value}
                    for field_name, value in result.informational
                ],
                disputed=has_disputed(requirements),
            )
        )

    order = [FitBand.REACH, FitBand.TARGET, FitBand.SAFER, FitBand.UNKNOWN]
    fits.sort(key=lambda fit: order.index(fit.band))
    return CompareProgramsOutput(
        data=fits, profile_missing=seen_missing, count=len(fits)
    )


COMPARE_PROGRAMS = ToolDefinition(
    name="compare_programs",
    description=(
        "根据当前用户档案比较最多八个项目，给出冲刺、匹配、稳妥分组及条件"
        "差距，同时返回截止日期、学费和背景要求。存在争议证据的项目会明确标记。"
    ),
    input_model=CompareProgramsInput,
    output_model=CompareProgramsOutput,
    permission_level=PermissionLevel.READ,
    handler=compare_programs,
)


GET_PROGRAM_REQUIREMENTS = ToolDefinition(
    name="get_program_requirements",
    description=(
        "读取一个项目已发布的录取要求，可限定申请季。状态为 conflict_pending "
        "的要求存在来源争议，不能当作已确认信息。"
    ),
    input_model=GetProgramRequirementsInput,
    output_model=GetProgramRequirementsOutput,
    permission_level=PermissionLevel.READ,
    handler=get_program_requirements,
)
