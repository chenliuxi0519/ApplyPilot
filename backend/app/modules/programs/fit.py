"""根据已发布要求给出可解释的项目匹配结果。"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.modules.profiles.models import UserProfile
from app.modules.programs.models import (
    ProgramRequirement,
    RequirementFieldName,
    RequirementStatus,
)


class FitBand(StrEnum):
    REACH = "reach"
    TARGET = "target"
    SAFER = "safer"

    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FitFactor:
    field: str
    required: str
    have: str
    delta: str
    """正数表示高于要求，负数表示仍有差距。"""


@dataclass(frozen=True)
class FitResult:
    band: FitBand
    strengths: tuple[FitFactor, ...]
    gaps: tuple[FitFactor, ...]
    informational: tuple[tuple[str, str], ...]
    """文本、日期和金额等不能直接比较的要求。"""

    profile_missing: tuple[str, ...]
    """项目有要求，但个人档案尚未填写的字段。"""


@dataclass(frozen=True)
class _NumericRule:
    profile_attr: str
    target_surplus: Decimal


_NUMERIC_RULES: dict[RequirementFieldName, _NumericRule] = {
    RequirementFieldName.IELTS_OVERALL: _NumericRule(
        profile_attr="ielts_overall", target_surplus=Decimal("0.5")
    ),
}

_INFO_FIELDS: frozenset[RequirementFieldName] = frozenset(
    {
        RequirementFieldName.DEGREE_BACKGROUND,
        RequirementFieldName.PREREQUISITE_COURSES,
        RequirementFieldName.APPLICATION_DEADLINE,
        RequirementFieldName.TUITION,
        RequirementFieldName.WORK_EXPERIENCE_YEARS,
        RequirementFieldName.TOEFL_OVERALL,
        RequirementFieldName.IELTS_MIN_BAND,
        RequirementFieldName.GPA_MIN,
        RequirementFieldName.GPA_SCALE,
    }
)


def _fmt(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return format(normalized, "f")


def _signed(delta: Decimal) -> str:
    return f"+{_fmt(delta)}" if delta >= 0 else f"-{_fmt(-delta)}"


def _requirement_display(requirement: ProgramRequirement) -> str:
    if requirement.numeric_value is not None:
        return _fmt(requirement.numeric_value)
    if requirement.date_value is not None:
        return requirement.date_value.isoformat()
    if requirement.money_amount is not None:
        return f"{_fmt(requirement.money_amount)} {requirement.money_currency}"
    if requirement.text_value is not None:
        return requirement.text_value
    if requirement.text_list_value is not None:
        return ", ".join(requirement.text_list_value)
    return ""


def evaluate_fit(
    profile: UserProfile | None,
    requirements: Sequence[ProgramRequirement],
) -> FitResult:
    strengths: list[FitFactor] = []
    gaps: list[FitFactor] = []
    informational: list[tuple[str, str]] = []
    missing: list[str] = []
    numeric_seen = 0

    surplus_ratios: list[Decimal] = []
    for requirement in requirements:
        if requirement.field_name in _NUMERIC_RULES:
            rule = _NUMERIC_RULES[requirement.field_name]
            required = requirement.numeric_value
            if required is None:
                continue
            numeric_seen += 1
            have_raw = (
                None if profile is None else getattr(profile, rule.profile_attr, None)
            )
            if have_raw is None:
                missing.append(rule.profile_attr)
                continue
            have = Decimal(have_raw)
            delta = have - Decimal(required)
            factor = FitFactor(
                field=requirement.field_name.value,
                required=_fmt(Decimal(required)),
                have=_fmt(have),
                delta=_signed(delta),
            )
            if delta < 0:
                gaps.append(factor)
                surplus_ratios.append(delta)
            else:
                strengths.append(factor)
                # 达到要求后，再用高出门槛的幅度区分“匹配”和“稳妥”。
                surplus_ratios.append(
                    delta / rule.target_surplus
                    if rule.target_surplus > 0
                    else Decimal(1)
                )
        elif requirement.field_name in _INFO_FIELDS:
            informational.append(
                (requirement.field_name.value, _requirement_display(requirement))
            )

    band = _band(gaps, strengths, surplus_ratios, numeric_seen)
    return FitResult(
        band=band,
        strengths=tuple(strengths),
        gaps=tuple(gaps),
        informational=tuple(informational),
        profile_missing=tuple(missing),
    )


def _band(
    gaps: list[FitFactor],
    strengths: list[FitFactor],
    surplus_ratios: list[Decimal],
    numeric_seen: int,
) -> FitBand:
    if numeric_seen == 0:
        return FitBand.UNKNOWN
    if gaps:
        return FitBand.REACH
    if not strengths:
        return FitBand.UNKNOWN
    return FitBand.SAFER if min(surplus_ratios) >= 1 else FitBand.TARGET


def has_disputed(requirements: Sequence[ProgramRequirement]) -> bool:
    return any(
        requirement.status is RequirementStatus.CONFLICT_PENDING
        for requirement in requirements
    )
