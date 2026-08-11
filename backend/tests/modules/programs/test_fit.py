import uuid
from datetime import date, datetime
from decimal import Decimal

from app.modules.profiles.models import UserProfile
from app.modules.programs.fit import FitBand, evaluate_fit, has_disputed
from app.modules.programs.models import (
    ProgramRequirement,
    RequirementFieldName,
    RequirementStatus,
    RequirementValueType,
)


def _profile(**kwargs) -> UserProfile:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
    }
    defaults.update(kwargs)
    return UserProfile(**defaults)  # type: ignore[arg-type]


def _requirement(
    field: RequirementFieldName,
    *,
    numeric: Decimal | None = None,
    text: str | None = None,
    date_value: date | None = None,
    status: RequirementStatus = RequirementStatus.PUBLISHED,
) -> ProgramRequirement:
    value_type = RequirementValueType.NUMERIC
    if text is not None:
        value_type = RequirementValueType.TEXT
    elif date_value is not None:
        value_type = RequirementValueType.DATE
    return ProgramRequirement(
        id=uuid.uuid4(),
        program_id=uuid.uuid4(),
        application_cycle="2026/27",
        field_name=field,
        value_type=value_type,
        status=status,
        numeric_value=numeric,
        text_value=text,
        date_value=date_value,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )


def test_a_comfortable_surplus_is_safer() -> None:
    result = evaluate_fit(
        _profile(ielts_overall=Decimal("7.5")),
        [_requirement(RequirementFieldName.IELTS_OVERALL, numeric=Decimal("6.0"))],
    )
    assert result.band is FitBand.SAFER
    assert result.gaps == ()
    assert result.strengths[0].delta == "+1.5"


def test_a_narrow_surplus_is_target() -> None:
    result = evaluate_fit(
        _profile(ielts_overall=Decimal("6.5")),
        [_requirement(RequirementFieldName.IELTS_OVERALL, numeric=Decimal("6.5"))],
    )
    assert result.band is FitBand.TARGET
    assert result.strengths[0].delta == "+0"


def test_a_deficit_is_reach() -> None:
    result = evaluate_fit(
        _profile(ielts_overall=Decimal("6.0")),
        [_requirement(RequirementFieldName.IELTS_OVERALL, numeric=Decimal("7.0"))],
    )
    assert result.band is FitBand.REACH
    assert result.gaps[0].delta == "-1"
    assert result.strengths == ()


def test_a_missing_profile_value_is_reported_not_invented() -> None:
    result = evaluate_fit(
        _profile(),
        [_requirement(RequirementFieldName.IELTS_OVERALL, numeric=Decimal("6.5"))],
    )
    assert result.band is FitBand.UNKNOWN
    assert result.gaps == ()
    assert "ielts_overall" in result.profile_missing


def test_no_profile_at_all_reports_every_missing_field() -> None:
    result = evaluate_fit(
        None,
        [_requirement(RequirementFieldName.IELTS_OVERALL, numeric=Decimal("6.5"))],
    )
    assert result.band is FitBand.UNKNOWN
    assert result.profile_missing == ("ielts_overall",)


def test_text_and_date_requirements_are_context_not_gaps() -> None:
    result = evaluate_fit(
        _profile(ielts_overall=Decimal("6.5")),
        [
            _requirement(
                RequirementFieldName.DEGREE_BACKGROUND, text="honours in computing"
            ),
            _requirement(
                RequirementFieldName.APPLICATION_DEADLINE, date_value=date(2026, 3, 31)
            ),
            _requirement(RequirementFieldName.IELTS_OVERALL, numeric=Decimal("6.0")),
        ],
    )
    fields = {name for name, _ in result.informational}
    assert "degree_background" in fields
    assert "application_deadline" in fields

    assert result.band is FitBand.SAFER


def test_a_disputed_requirement_still_counts_and_is_flagged() -> None:
    disputed = _requirement(
        RequirementFieldName.IELTS_OVERALL,
        numeric=Decimal("7.5"),
        status=RequirementStatus.CONFLICT_PENDING,
    )
    result = evaluate_fit(_profile(ielts_overall=Decimal("6.5")), [disputed])
    assert result.band is FitBand.REACH
    assert has_disputed([disputed])


def test_no_requirements_at_all_is_unknown() -> None:
    result = evaluate_fit(_profile(ielts_overall=Decimal("6.5")), [])
    assert result.band is FitBand.UNKNOWN
    assert result.gaps == () and result.strengths == ()


def test_the_worst_factor_decides_the_band() -> None:
    result = evaluate_fit(
        _profile(ielts_overall=Decimal("6.0")),
        [
            _requirement(RequirementFieldName.IELTS_OVERALL, numeric=Decimal("6.5")),
        ],
    )
    assert result.band is FitBand.REACH
